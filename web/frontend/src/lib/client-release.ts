// 公开安装包只有一个来源；平台发布记录不覆盖已核实的 GitHub 正式发行。
export const clientRelease = {
  version: "0.9.0",
  publishedAt: "2026-10-25",
  filename: "Xuansi-0.9.0-windows-x64-setup.exe",
  bytes: 28909100,
  sha256: "E2E1EF9154C4C2BB3596DB0FA2300A87DEBBF5A0868ABE1F1BDA1797ACFC5EEE",
  signing: "unsigned",
  highlights: [
    "对话页新增使用检查，说明 AI 配置与下一步；模型或密钥有草稿时，先保存再发送。",
    "收到有效文字回复后完成首次引导。遇到服务或资源问题，可直接前往对应设置处理。",
    "试听未播放会说明静音或声音回避原因；软件内反馈入口支持访客提交，失败保留草稿。",
  ],
  downloadUrl:
    "https://github.com/DesktopPetXuansi/Xuansi/releases/download/v0.9.0/Xuansi-0.9.0-windows-x64-setup.exe",
  releaseUrl: "https://github.com/DesktopPetXuansi/Xuansi/releases/tag/v0.9.0",
  checksumUrl:
    "https://github.com/DesktopPetXuansi/Xuansi/releases/download/v0.9.0/SHA256SUMS.txt",
} as const;
