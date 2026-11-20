"""Multi-view Operation embeddings with BGE-M3 and an explicit offline smoke backend.

The lexical backend produces hashed ngram vectors, NOT BGE embeddings. It is
provided for deterministic offline tests and is never silently substituted.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import numpy as np
from .graph import Graph,json_value,distinct


TOKEN_PATTERN=re.compile(r'[A-Za-z0-9_./-]+|[\u3400-\u9fff]+')


def lexical_tokens(text):
    result=[]
    for match in TOKEN_PATTERN.findall(text.lower()):
        if re.search(r'[\u3400-\u9fff]',match):
            result.extend(match[i:i+2] for i in range(max(0,len(match)-1)))
            result.extend(match[i:i+3] for i in range(max(0,len(match)-2)))
        else:
            result.append(match)
            result.extend(x for x in match.split('_') if x and x!=match)
    return result


class VectorEncoder:
    def __init__(self,backend='bge-m3',model='BAAI/bge-m3',device='cpu',dimensions=4096):
        if backend not in ('bge-m3','lexical'):raise ValueError('Unknown backend')
        self.backend=backend;self.model=model if backend=='bge-m3' else 'deterministic-char-ngram-v1'
        self.device=device;self.dimensions=dimensions
        self._model=None

    def encode(self,texts,batch_size=16):
        if not texts:return np.zeros((0,self.dimensions if self.backend=='lexical' else 0),dtype='float32')
        if self.backend=='lexical':
            result=np.zeros((len(texts),self.dimensions),dtype=np.float32)
            for i,txt in enumerate(texts):
                for token in lexical_tokens(txt):
                    h=int.from_bytes(hashlib.blake2b(token.encode('utf-8'),digest_size=8).digest(),'big')
                    result[i,h%self.dimensions]+=1
        else:
            if self._model is None:
                try:from sentence_transformers import SentenceTransformer
                except ImportError as exc:
                    raise RuntimeError('BGE-M3 requires: pip install sentence-transformers; for offline smoke tests use --backend lexical') from exc
                device=self.device
                if device=='auto':
                    try:
                        import torch
                        device='cuda' if torch.cuda.is_available() else 'cpu'
                    except ImportError:device='cpu'
                self._model=SentenceTransformer(self.model,device=device,trust_remote_code=False)
            result=np.asarray(self._model.encode(texts,batch_size=batch_size,convert_to_numpy=True,normalize_embeddings=True,show_progress_bar=False),dtype=np.float32)
        norm=np.linalg.norm(result,axis=1,keepdims=True)
        return result/np.maximum(norm,1e-9)


def operation_views(graph:Graph):
    entries=[]
    for oid,node in sorted(graph.operations.items()):
        op=node['properties']; tool_id,tool=graph.available_tool_info(oid)
        toolname=tool.get('name','');tasks=[graph.get(t).get('name','') for t in graph.op_tasks.get(oid,[])]
        prefix=f"工具 Tool: {toolname}; 操作 Operation: {op.get('name','')};"
        purpose=f"{prefix} 功能 Purpose: {op.get('description','')}; 任务 Task: {'; '.join(tasks)}"
        scenarios=json_value(op.get('scenarios_json'),[])
        scenetext='; '.join(str(s.get(k,'')) for s in scenarios for k in ('name','description') if isinstance(s,dict))
        if not scenetext: scenetext='; '.join(tasks)
        scene=f'{prefix} 应用场景 Scenario: {scenetext}'
        inp=graph.operation_ports(oid,'input');out=graph.operation_ports(oid,'output')
        def desc(ps):
            return '; '.join(f"{x.get('data_type','')} {x.get('description','')} 格式:{','.join(x.get('formats') or [])} 状态:{x.get('semantic_facets') or {}}" for x in ps)
        io=f'{prefix} 输入 Input: {desc(inp)}; 输出 Output: {desc(out)}'
        for view,text in [('purpose',purpose),('scenario',scene),('io',io)]:
            entries.append({'id':oid,'view':view,'text':text})
    for did,n in sorted(graph.datatypes.items()):
        p=n['properties']; parents=[graph.get(e.target).get('name','') for e in graph.from_node(did,'IS_SUBTYPE_OF')]
        entries.append({'id':did,'view':'datatype','text':f"DataType 数据类型: {p.get('name','')}; 定义: {p.get('description','')}; 父类型: {' '.join(parents)}"})
    for tid,n in sorted(graph.tools.items()):
        if n['properties'].get('stub'):continue
        p=n['properties'];entries.append({'id':tid,'view':'tool','text':f"Tool 科研工具: {p.get('name','')}; 功能: {p.get('description','')}"})
    return entries


class SemanticIndex:
    def __init__(self,metadata,vectors):
        self.metadata=metadata;self.entries=metadata['entries'];self.vectors=np.asarray(vectors,dtype=np.float32)
        if len(self.entries)!=len(self.vectors):raise ValueError('metadata/vector count mismatch')
        if self.vectors.ndim!=2:raise ValueError('vectors must be matrix')
        self.backend=metadata['backend'];self.model=metadata['model']

    @classmethod
    def build(cls,graph,backend='bge-m3',model='BAAI/bge-m3',device='cpu',batch_size=16):
        encoder=VectorEncoder(backend,model,device)
        entries=operation_views(graph)
        vectors=encoder.encode([e['text'] for e in entries],batch_size=batch_size)
        metadata={'version':'bioskill-op-index-1','backend':backend,'model':encoder.model,
                  'digest':graph.digest,'entries':entries,'dimension':int(vectors.shape[1])}
        return cls(metadata,vectors)

    def save(self,folder):
        path=Path(folder);path.mkdir(parents=True,exist_ok=True)
        (path/'metadata.json').write_text(json.dumps(self.metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        np.save(path/'vectors.npy',self.vectors,allow_pickle=False)

    @classmethod
    def load(cls,folder,graph=None):
        p=Path(folder)
        metadata=json.loads((p/'metadata.json').read_text(encoding='utf-8'))
        arr=np.load(p/'vectors.npy',allow_pickle=False)
        obj=cls(metadata,arr)
        if graph is not None and graph.digest!=metadata['digest']:
            raise ValueError('Graph changed since vectors were built. Regenerate index before querying.')
        return obj

    def search(self,text,encoder,k=15,allowed_views=None):
        if encoder.backend!=self.backend or encoder.model!=self.model:
            raise ValueError('Index and query encoder mismatch')
        q=encoder.encode([text])[0]
        sims=self.vectors@q
        candidates=[]
        for i,e in enumerate(self.entries):
            if allowed_views and e['view'] not in allowed_views:continue
            candidates.append({'id':e['id'],'view':e['view'],'score':float(sims[i]),'text':e['text']})
        candidates.sort(key=lambda x:-x['score'])
        return candidates[:k]
