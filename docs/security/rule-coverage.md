# 教程规则与本项目检测器对应

保留原有 41 项检测标识。下表对应教程 25 项行为，不重复建立等效规则；实际数量以统一目录为准。

| 教程 | 本项目 rule_id |
|---|---|
| credential.secret_token | credential_apikey_openai / generic / google、credential_jwt、credential_github_pat、credential_bearer |
| credential.private_key | credential_private_key、credential_private_key_rsa |
| credential.named_secret | credential_named_secret；password/token/secret 文本赋值规则 |
| credential.database_url | credential_database_url |
| credential.cloud_key | credential_aws_access、credential_cloud_key |
| file.sensitive_path | file_sensitive_path |
| file.ssh_key | file_ssh_key |
| file.cloud_credentials | file_sensitive_path |
| infra.local_path | infra_local_path、path_absolute_win |
| personal.email | personal_email |
| personal.phone | personal_phone |
| unicode.zero_width | unicode_zero_width |
| unicode.bidi_control | unicode_zero_width、unicode_right_to_left |
| unicode.variation_selector | unicode_variation_selector |
| unicode.homograph | unicode_homoglyph_cyrillic、unicode_homoglyph_greek |
| network.ip_probe | network_ip_probe |
| network.suspicious_domain | network_suspicious_domain |
| network.external_url | network_url_http、network_external_url |
| network.tracking_pixel | network_tracking_pixel；原有 tracking_* 继续保留 |
| tool.shell.network_or_exec | tool_shell_network_or_exec、tool_cmd_exec |
| tool.shell.exfiltration | tool_shell_exfiltration |
| tool.remote_script_exec | tool_remote_script_exec |
| tool.git_info | tool_git_info |
| prompt.fingerprint_context | prompt_fingerprint_context |
| prompt.injection | tool_prompt_injection |

内置检测机制由代码维护；数据库存储可编辑策略。已有配置不会被启动播种覆盖。
