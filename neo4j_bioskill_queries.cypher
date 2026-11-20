// 1) Cross-document tool chain: BWA -> bcftools -> ANNOVAR
MATCH p=(a:BioSkillEntity:Tool {canonical_name:'bwa'})
-[:DOCUMENTED_DOWNSTREAM]->(:BioSkillEntity:Tool {canonical_name:'bcftools'})
-[:DOCUMENTED_DOWNSTREAM]->(:BioSkillEntity:Tool {canonical_name:'annovar'})
RETURN p;

// 2) All bcftools operations
MATCH p=(t:BioSkillEntity:Tool {canonical_name:'bcftools'})
-[:HAS_OPERATION]->(o:BioSkillEntity:Operation)
RETURN p;

// 3) Input/output/task edges for bcftools filter
MATCH p=(op:BioSkillEntity:Operation {name:'bcftools filter'})-[r]->(n:BioSkillEntity)
RETURN p LIMIT 30;

// 4) Show references/evidence for bcftools -> ANNOVAR relations
MATCH (a:BioSkillEntity:Tool {canonical_name:'bcftools'})-[r]->(b:BioSkillEntity:Tool {canonical_name:'annovar'})
RETURN a.name AS source, type(r) AS relation, b.name AS target,
       r.source_files AS files, r.source_sections AS evidence;

// 5) All Tool nodes, check stub flag after incremental completion
MATCH (n:BioSkillEntity:Tool)
RETURN n.canonical_name AS tool, n.stub AS is_placeholder, n.version AS version
ORDER BY tool;

// 6) View the small KG
MATCH p=(a:BioSkillEntity)-[r]->(b:BioSkillEntity)
RETURN p LIMIT 150;


// 7) Inspect each DataType -> FileFormat edge with its own evidence and section.
MATCH (d:BioSkillEntity:DataType)-[r:HAS_FORMAT]->(f:BioSkillEntity:FileFormat)
RETURN d.id AS data_type_id, d.name AS data_type,
       f.name AS file_format, r.evidence_quotes AS format_evidence,
       r.source_files AS source_files, r.source_sections AS source_sections
ORDER BY data_type_id, file_format;

// 8) Find HAS_FORMAT relationships missing their own evidence (expected: 0 rows).
MATCH (d:BioSkillEntity:DataType)-[r:HAS_FORMAT]->(f:BioSkillEntity:FileFormat)
WHERE r.evidence_quotes IS NULL OR size(r.evidence_quotes) = 0
RETURN d.id AS data_type_id, f.name AS file_format;
