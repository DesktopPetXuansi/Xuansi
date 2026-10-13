-- +goose Up
-- 仅登记已经发布的真实安装包，不制造下载数或官方模型资源。
INSERT INTO client_releases(id,version,channel,source_commit,release_notes,published_at) VALUES('00000000-0000-4000-8000-000000000056','0.5.6','STABLE','bc3f61e43937289701765386233d4661bc90f74d','Windows 在线安装版；网站资源接入功能需后续客户端版本。','2026-10-11T13:59:36Z');
INSERT INTO release_artifacts(id,release_id,os,arch,distribution_type,download_url,sha256,bytes,system_requirements) VALUES('00000000-0000-4000-8000-000000000057','00000000-0000-4000-8000-000000000056','windows','x64','ONLINE_INSTALLER','https://github.com/DesktopPetXuansi/Xuansi/releases/download/v0.5.6/Xuansi-0.5.6-windows-x64-setup.exe','f6628478ab66a3ae5944280371e0cfd1cb7fa22ee75c6980812251f72f2a4427',28300434,'["Windows 11 x64","NVIDIA GPU 与 CUDA 12.4","D盘及充足磁盘空间","首次安装需要联网下载AI模型"]');
-- +goose Down
DELETE FROM release_artifacts WHERE id='00000000-0000-4000-8000-000000000057';
DELETE FROM client_releases WHERE id='00000000-0000-4000-8000-000000000056';
