ALTER TABLE knowledge_base_files
    ADD COLUMN IF NOT EXISTS chunk_strategy VARCHAR(64) DEFAULT 'character';
ALTER TABLE knowledge_base_files
    ADD COLUMN IF NOT EXISTS chunk_strategy_version VARCHAR(64);
ALTER TABLE knowledge_base_files
    ADD COLUMN IF NOT EXISTS chunk_size INTEGER;
ALTER TABLE knowledge_base_files
    ADD COLUMN IF NOT EXISTS chunk_overlap INTEGER;
