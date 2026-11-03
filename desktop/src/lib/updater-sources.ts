// 更新源配置 - 当前仅 GitHub 单源
// 如需添加镜像源,在 updater-config.json 中添加,并在 tauri.conf.json endpoints 中同步配置

export type UpdaterSource = {
  id: string;
  label: string;
  latestJsonUrl: string;
};

// Python desktop releases must never install the upstream Rust binary.
export const SOURCES: UpdaterSource[] = [];
