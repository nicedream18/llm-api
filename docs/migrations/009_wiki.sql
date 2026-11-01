-- Logical Wiki paths never map to filesystem paths.
CREATE TABLE IF NOT EXISTS wiki_projects (
    id VARCHAR(64) PRIMARY KEY, name VARCHAR(128) NOT NULL,
    description TEXT NOT NULL, created_at VARCHAR(32) NOT NULL, updated_at VARCHAR(32) NOT NULL
);
CREATE TABLE IF NOT EXISTS wiki_pages (
    id VARCHAR(64) PRIMARY KEY, project_id VARCHAR(64) NOT NULL,
    path VARCHAR(384) NOT NULL, title VARCHAR(256) NOT NULL, content MEDIUMTEXT NOT NULL,
    tags TEXT NOT NULL, revision INTEGER NOT NULL,
    created_at VARCHAR(32) NOT NULL, updated_at VARCHAR(32) NOT NULL,
    UNIQUE (project_id, path),
    FOREIGN KEY (project_id) REFERENCES wiki_projects(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS wiki_sources (
    id VARCHAR(64) PRIMARY KEY, project_id VARCHAR(64) NOT NULL,
    filename VARCHAR(256) NOT NULL, content MEDIUMTEXT NOT NULL,
    status VARCHAR(16) NOT NULL, page_id VARCHAR(64), error_message TEXT,
    created_at VARCHAR(32) NOT NULL, updated_at VARCHAR(32) NOT NULL,
    FOREIGN KEY (project_id) REFERENCES wiki_projects(id) ON DELETE CASCADE,
    FOREIGN KEY (page_id) REFERENCES wiki_pages(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS wiki_attachments (
    id VARCHAR(64) PRIMARY KEY, project_id VARCHAR(64) NOT NULL,
    page_id VARCHAR(64) NOT NULL, filename VARCHAR(256) NOT NULL,
    media_type VARCHAR(128) NOT NULL, content MEDIUMBLOB NOT NULL,
    created_at VARCHAR(32) NOT NULL,
    FOREIGN KEY (project_id) REFERENCES wiki_projects(id) ON DELETE CASCADE,
    FOREIGN KEY (page_id) REFERENCES wiki_pages(id) ON DELETE CASCADE
);
