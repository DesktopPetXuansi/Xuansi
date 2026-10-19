// 公开安装包只有一个来源；平台发布记录不覆盖已核实的 GitHub 正式发行。
export const clientRelease = {
  version: "0.8.0",
  publishedAt: "2026-10-19",
  downloadUrl:
    "https://github.com/DesktopPetXuansi/Xuansi/releases/download/v0.8.0/Xuansi-0.8.0-windows-x64-setup.exe",
  releaseUrl: "https://github.com/DesktopPetXuansi/Xuansi/releases/tag/v0.8.0",
  checksumUrl:
    "https://github.com/DesktopPetXuansi/Xuansi/releases/download/v0.8.0/SHA256SUMS.txt",
} as const;
