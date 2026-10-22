// 公开安装包只有一个来源；平台发布记录不覆盖已核实的 GitHub 正式发行。
export const clientRelease = {
  version: "0.8.0",
  publishedAt: "2026-10-19",
  filename: "Xuansi-0.8.0-windows-x64-setup.exe",
  bytes: 29192720,
  sha256: "5C19FED990BBA1019F67A026BEC4C4C9F9891C535210D5454474B3C5656370B3",
  signing: "unsigned",
  highlights: [
    "在「在线挑选 / 我的形象」选中后直接使用，自动下载、检查并切换，完整副本可复用。",
    "预览成为可选操作；取消或加载失败会保留原形象，成功切换后才保存历史。",
    "支持回选本机形象和 AI 配置历史。形象历史同步默认关闭，AI 配置历史留在本机。",
  ],
  downloadUrl:
    "https://github.com/DesktopPetXuansi/Xuansi/releases/download/v0.8.0/Xuansi-0.8.0-windows-x64-setup.exe",
  releaseUrl: "https://github.com/DesktopPetXuansi/Xuansi/releases/tag/v0.8.0",
  checksumUrl:
    "https://github.com/DesktopPetXuansi/Xuansi/releases/download/v0.8.0/SHA256SUMS.txt",
} as const;
