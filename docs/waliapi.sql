-- ============================================================
-- WaLiAPI 数据库 DDL
-- 数据库: waliapi
-- 字符集: utf8mb4
-- 创建日期: 2026-07-28
-- ============================================================

SET NAMES utf8mb4;
CREATE DATABASE IF NOT EXISTS waliapi DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE waliapi;

-- ============================================================
-- 1. channels - 渠道表
-- ============================================================
CREATE TABLE IF NOT EXISTS `channels` (
  `id` VARCHAR(64) NOT NULL COMMENT '渠道ID',
  `name` VARCHAR(128) NOT NULL COMMENT '渠道名称',
  `type` VARCHAR(32) NOT NULL COMMENT '渠道类型(openai/anthropic/custom)',
  `base_url` VARCHAR(512) DEFAULT NULL COMMENT '上游基础URL',
  `api_key` VARCHAR(512) DEFAULT NULL COMMENT '上游API密钥',
  `models` TEXT COMMENT '支持的模型列表(JSON数组)',
  `status` TINYINT DEFAULT 1 COMMENT '状态: 0=禁用 1=启用',
  `priority` INT DEFAULT 0 COMMENT '优先级(越大越优先)',
  `weight` INT DEFAULT 1 COMMENT '权重(同优先级时负载均衡)',
  `config` TEXT COMMENT '渠道额外配置(JSON)',
  `model_mapping` TEXT COMMENT '模型名映射(JSON, key=请求模型 value=上游模型)',
  `last_test_at` VARCHAR(32) DEFAULT NULL COMMENT '最后测试时间',
  `last_test_ok` TINYINT DEFAULT NULL COMMENT '最后测试结果: 0=失败 1=成功',
  `created_at` VARCHAR(32) NOT NULL COMMENT '创建时间',
  `updated_at` VARCHAR(32) NOT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='渠道表';

-- ============================================================
-- 2. api_keys - API密钥表
-- ============================================================
CREATE TABLE IF NOT EXISTS `api_keys` (
  `id` VARCHAR(64) NOT NULL COMMENT '密钥ID',
  `name` VARCHAR(128) NOT NULL COMMENT '密钥名称',
  `key` VARCHAR(128) NOT NULL COMMENT 'API Key',
  `status` TINYINT DEFAULT 1 COMMENT '状态: 0=禁用 1=启用',
  `allowed_models` TEXT COMMENT '允许的模型列表(JSON数组, 为空=全部允许)',
  `allowed_channels` TEXT COMMENT '允许的渠道列表(JSON数组, 为空=全部允许)',
  `quota_limit` BIGINT DEFAULT 0 COMMENT '额度上限(0=不限)',
  `quota_used` BIGINT DEFAULT 0 COMMENT '已用额度',
  `expires_at` VARCHAR(32) DEFAULT NULL COMMENT '过期时间(为空=永不过期)',
  `created_at` VARCHAR(32) NOT NULL COMMENT '创建时间',
  `updated_at` VARCHAR(32) NOT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_key` (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='API密钥表';

-- ============================================================
-- 3. request_logs - 请求日志表
-- ============================================================
CREATE TABLE IF NOT EXISTS `request_logs` (
  `id` VARCHAR(64) NOT NULL COMMENT '日志ID',
  `seq` BIGINT NOT NULL AUTO_INCREMENT COMMENT '自增序列号',
  `api_key_id` VARCHAR(64) DEFAULT NULL COMMENT 'API密钥ID',
  `api_key_name` VARCHAR(128) DEFAULT NULL COMMENT 'API密钥名称',
  `channel_id` VARCHAR(64) DEFAULT NULL COMMENT '渠道ID',
  `channel_name` VARCHAR(128) DEFAULT NULL COMMENT '渠道名称',
  `model` VARCHAR(128) NOT NULL COMMENT '请求模型',
  `upstream_model` VARCHAR(128) DEFAULT NULL COMMENT '上游实际模型',
  `mode` VARCHAR(32) DEFAULT NULL COMMENT '调用模式(chat/completion/embedding)',
  `status_code` INT DEFAULT NULL COMMENT 'HTTP状态码',
  `prompt_tokens` BIGINT DEFAULT 0 COMMENT '提示词Token数',
  `completion_tokens` BIGINT DEFAULT 0 COMMENT '完成Token数',
  `total_tokens` BIGINT DEFAULT 0 COMMENT '总Token数',
  `duration_ms` BIGINT DEFAULT 0 COMMENT '耗时(毫秒)',
  `error_message` TEXT COMMENT '错误信息',
  `is_stream` TINYINT DEFAULT 0 COMMENT '是否流式: 0=否 1=是',
  `is_retry` TINYINT DEFAULT 0 COMMENT '是否重试: 0=否 1=是',
  `request_body` MEDIUMTEXT COMMENT '请求体',
  `response_choices` MEDIUMTEXT COMMENT '响应内容',
  `risk_level` VARCHAR(16) DEFAULT 'Clean' COMMENT '风险等级(Clean/Low/Medium/High/Critical)',
  `risk_score` INT DEFAULT 0 COMMENT '风险评分',
  `risk_summary` TEXT COMMENT '风险摘要',
  `security_action` VARCHAR(32) DEFAULT 'Allow' COMMENT '安全动作(Allow/Sanitize/Block)',
  `sanitized` TINYINT DEFAULT 0 COMMENT '是否已脱敏: 0=否 1=是',
  `blocked_reason` TEXT COMMENT '阻断原因',
  `trace_id` VARCHAR(64) DEFAULT NULL COMMENT '链路追踪ID',
  `created_at` VARCHAR(32) NOT NULL COMMENT '创建时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_seq` (`seq`),
  KEY `idx_created_at` (`created_at`),
  KEY `idx_api_key` (`api_key_id`),
  KEY `idx_channel` (`channel_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='请求日志表';

-- ============================================================
-- 4. security_findings - 安全发现表
-- ============================================================
CREATE TABLE IF NOT EXISTS `security_findings` (
  `id` VARCHAR(64) NOT NULL COMMENT '发现ID',
  `log_id` VARCHAR(64) NOT NULL COMMENT '关联请求日志ID',
  `phase` VARCHAR(32) DEFAULT NULL COMMENT '检测阶段(request/response)',
  `category` VARCHAR(64) DEFAULT NULL COMMENT '安全分类',
  `rule_id` VARCHAR(128) DEFAULT NULL COMMENT '触发的规则ID',
  `severity` VARCHAR(16) DEFAULT NULL COMMENT '严重级别(Info/Low/Medium/High/Critical)',
  `title` VARCHAR(256) DEFAULT NULL COMMENT '发现标题',
  `description` TEXT COMMENT '详细描述',
  `location` VARCHAR(512) DEFAULT NULL COMMENT '发现位置',
  `evidence_masked` TEXT COMMENT '脱敏后的证据',
  `evidence_hash` VARCHAR(128) DEFAULT NULL COMMENT '证据哈希',
  `action` VARCHAR(32) DEFAULT NULL COMMENT '处置动作(Allow/Sanitize/Block)',
  `created_at` VARCHAR(32) NOT NULL COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_log_id` (`log_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='安全发现表';

-- ============================================================
-- 5. security_builtin_rules - 内置安全规则
-- ============================================================
CREATE TABLE IF NOT EXISTS `security_builtin_rules` (
  `id` VARCHAR(64) NOT NULL COMMENT '规则ID',
  `rule_id` VARCHAR(128) NOT NULL COMMENT '规则唯一标识',
  `category` VARCHAR(64) DEFAULT NULL COMMENT '安全分类',
  `severity` VARCHAR(16) DEFAULT NULL COMMENT '严重级别',
  `title` VARCHAR(256) DEFAULT NULL COMMENT '规则标题',
  `description` TEXT COMMENT '规则描述',
  `toggle_key` VARCHAR(128) DEFAULT NULL COMMENT '开关配置键',
  `enabled` TINYINT DEFAULT 1 COMMENT '是否启用: 0=否 1=是',
  `created_at` VARCHAR(32) NOT NULL COMMENT '创建时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_rule_id` (`rule_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='内置安全规则';

-- ============================================================
-- 6. security_custom_rules - 自定义安全规则
-- ============================================================
CREATE TABLE IF NOT EXISTS `security_custom_rules` (
  `id` VARCHAR(64) NOT NULL COMMENT '规则ID',
  `rule_type` VARCHAR(32) DEFAULT NULL COMMENT '规则类型(regex/keyword/semantic)',
  `category` VARCHAR(64) DEFAULT NULL COMMENT '安全分类',
  `pattern` TEXT COMMENT '匹配模式/正则表达式',
  `severity` VARCHAR(16) DEFAULT NULL COMMENT '严重级别',
  `action` VARCHAR(32) DEFAULT NULL COMMENT '处置动作(Allow/Sanitize/Block)',
  `enabled` TINYINT DEFAULT 1 COMMENT '是否启用: 0=否 1=是',
  `description` TEXT COMMENT '规则描述',
  `created_at` VARCHAR(32) NOT NULL COMMENT '创建时间',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='自定义安全规则';

-- ============================================================
-- 7. kb_knowledge_bases - 知识库表
-- ============================================================
CREATE TABLE IF NOT EXISTS `kb_knowledge_bases` (
  `id` VARCHAR(64) NOT NULL COMMENT '知识库ID',
  `name` VARCHAR(128) NOT NULL COMMENT '知识库名称',
  `description` TEXT COMMENT '描述',
  `tags` TEXT COMMENT '标签(JSON数组)',
  `chunk_size` INT DEFAULT 512 COMMENT '分块大小',
  `chunk_overlap` INT DEFAULT 50 COMMENT '分块重叠',
  `created_at` VARCHAR(32) NOT NULL COMMENT '创建时间',
  `updated_at` VARCHAR(32) NOT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库表';

-- ============================================================
-- 8. kb_documents - 知识库文档表
-- ============================================================
CREATE TABLE IF NOT EXISTS `kb_documents` (
  `id` VARCHAR(64) NOT NULL COMMENT '文档ID',
  `kb_id` VARCHAR(64) NOT NULL COMMENT '知识库ID',
  `name` VARCHAR(256) NOT NULL COMMENT '文档名称',
  `source_type` VARCHAR(32) DEFAULT NULL COMMENT '来源类型(file/url/text)',
  `source_path` VARCHAR(512) DEFAULT NULL COMMENT '来源路径',
  `status` VARCHAR(32) DEFAULT NULL COMMENT '状态(pending/processing/ready/error)',
  `chunk_count` INT DEFAULT 0 COMMENT '分块数量',
  `total_tokens` INT DEFAULT 0 COMMENT '总Token数',
  `error_message` TEXT COMMENT '错误信息',
  `created_at` VARCHAR(32) NOT NULL COMMENT '创建时间',
  `updated_at` VARCHAR(32) NOT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_kb_id` (`kb_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库文档表';

-- ============================================================
-- 9. kb_chunks - 知识库分块表
-- ============================================================
CREATE TABLE IF NOT EXISTS `kb_chunks` (
  `id` VARCHAR(64) NOT NULL COMMENT '分块ID',
  `doc_id` VARCHAR(64) NOT NULL COMMENT '文档ID',
  `kb_id` VARCHAR(64) NOT NULL COMMENT '知识库ID',
  `content` MEDIUMTEXT COMMENT '分块内容',
  `chunk_index` INT DEFAULT NULL COMMENT '分块索引',
  `token_count` INT DEFAULT NULL COMMENT 'Token数量',
  `embedding` BLOB COMMENT '嵌入向量',
  `chunk_type` VARCHAR(32) DEFAULT NULL COMMENT '分块类型',
  `language` VARCHAR(32) DEFAULT NULL COMMENT '语言',
  `metadata` TEXT COMMENT '元数据(JSON)',
  `created_at` VARCHAR(32) NOT NULL COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_doc_id` (`doc_id`),
  KEY `idx_kb_id` (`kb_id`),
  FULLTEXT KEY `ft_content` (`content`) WITH PARSER ngram
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库分块表';

-- ============================================================
-- 10a. kb_knowledge_bases 扩展列
-- ============================================================
ALTER TABLE `kb_knowledge_bases`
  ADD COLUMN IF NOT EXISTS `status` TINYINT DEFAULT 1 COMMENT '状态: 0=禁用 1=启用' AFTER `chunk_overlap`,
  ADD COLUMN IF NOT EXISTS `embedding_model` VARCHAR(128) DEFAULT NULL COMMENT '嵌入模型名称' AFTER `status`,
  ADD COLUMN IF NOT EXISTS `embedding_channel_id` VARCHAR(64) DEFAULT NULL COMMENT '嵌入渠道ID' AFTER `embedding_model`,
  ADD COLUMN IF NOT EXISTS `embedding_dim` INT DEFAULT 0 COMMENT '嵌入向量维度' AFTER `embedding_channel_id`,
  ADD COLUMN IF NOT EXISTS `index_status` VARCHAR(32) DEFAULT 'none' COMMENT '索引状态(none/pending/indexing/ready/error)' AFTER `embedding_dim`;

-- ============================================================
-- 10b. kb_tasks - 知识库任务表
-- ============================================================
CREATE TABLE IF NOT EXISTS `kb_tasks` (
  `id` VARCHAR(64) NOT NULL COMMENT '任务ID',
  `kb_id` VARCHAR(64) NOT NULL COMMENT '知识库ID',
  `doc_id` VARCHAR(64) DEFAULT NULL COMMENT '关联文档ID',
  `task_type` VARCHAR(32) NOT NULL COMMENT '任务类型(import/embed/index)',
  `status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '任务状态(pending/running/completed/failed)',
  `progress` INT DEFAULT 0 COMMENT '进度百分比',
  `total_items` INT DEFAULT 0 COMMENT '总条目数',
  `done_items` INT DEFAULT 0 COMMENT '已完成条目数',
  `error_message` TEXT COMMENT '错误信息',
  `created_at` VARCHAR(32) NOT NULL COMMENT '创建时间',
  `completed_at` VARCHAR(32) DEFAULT NULL COMMENT '完成时间',
  PRIMARY KEY (`id`),
  KEY `idx_kb_id` (`kb_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库任务表';

-- ============================================================
-- 10c. kb_conversations - 知识库对话历史表
-- ============================================================
CREATE TABLE IF NOT EXISTS `kb_conversations` (
  `id` VARCHAR(64) NOT NULL COMMENT '记录ID',
  `kb_id` VARCHAR(64) NOT NULL COMMENT '知识库ID',
  `role` VARCHAR(32) NOT NULL COMMENT '角色(user/assistant)',
  `content` TEXT NOT NULL COMMENT '内容',
  `sources` TEXT COMMENT '来源信息(JSON)',
  `model` VARCHAR(128) DEFAULT NULL COMMENT '使用的模型',
  `tokens_used` INT DEFAULT 0 COMMENT '消耗Token数',
  `created_at` VARCHAR(32) NOT NULL COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_kb_id` (`kb_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库对话历史表';

-- ============================================================
-- 10d. kb_sources - 知识库来源表
-- ============================================================
CREATE TABLE IF NOT EXISTS `kb_sources` (
  `id` VARCHAR(64) NOT NULL COMMENT '来源ID',
  `kb_id` VARCHAR(64) NOT NULL COMMENT '知识库ID',
  `source_type` VARCHAR(32) NOT NULL COMMENT '来源类型(git/url/local_dir)',
  `source_url` VARCHAR(512) DEFAULT NULL COMMENT '来源URL',
  `source_path` VARCHAR(512) DEFAULT NULL COMMENT '来源路径',
  `branch` VARCHAR(128) DEFAULT NULL COMMENT '分支',
  `status` VARCHAR(32) DEFAULT 'pending' COMMENT '状态',
  `file_count` INT DEFAULT 0 COMMENT '文件数量',
  `error` TEXT COMMENT '错误信息',
  `created_at` VARCHAR(32) NOT NULL COMMENT '创建时间',
  `updated_at` VARCHAR(32) NOT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_kb_id` (`kb_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库来源表';

-- ============================================================
-- 10e. kb_index_meta - 索引元数据表
-- ============================================================
CREATE TABLE IF NOT EXISTS `kb_index_meta` (
  `kb_id` VARCHAR(64) NOT NULL COMMENT '知识库ID',
  `index_type` VARCHAR(32) NOT NULL DEFAULT 'hnsw' COMMENT '索引类型',
  `embedding_dim` INT DEFAULT 0 COMMENT '向量维度',
  `chunk_count` INT DEFAULT 0 COMMENT '分块数量',
  `index_path` VARCHAR(512) DEFAULT NULL COMMENT '索引文件路径',
  `built_at` VARCHAR(32) DEFAULT NULL COMMENT '构建时间',
  `status` VARCHAR(32) DEFAULT 'none' COMMENT '状态(none/building/ready/error)',
  PRIMARY KEY (`kb_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='索引元数据表';

-- ============================================================
-- 10. agent_configs - Agent配置表
-- ============================================================
CREATE TABLE IF NOT EXISTS `agent_configs` (
  `id` VARCHAR(64) NOT NULL COMMENT '配置ID',
  `agent_id` VARCHAR(128) NOT NULL COMMENT 'Agent唯一标识',
  `agent_name` VARCHAR(128) NOT NULL COMMENT 'Agent名称',
  `agent_desc` TEXT COMMENT 'Agent描述',
  `app_name` VARCHAR(128) DEFAULT NULL COMMENT '应用名称',
  `config_json` MEDIUMTEXT COMMENT '配置内容(JSON)',
  `status` TINYINT DEFAULT 1 COMMENT '状态: 0=禁用 1=启用',
  `created_at` VARCHAR(32) NOT NULL COMMENT '创建时间',
  `updated_at` VARCHAR(32) NOT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_agent_id` (`agent_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Agent配置表';
