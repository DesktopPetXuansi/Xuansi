import { api } from "@/lib/api";
import type { Upload } from "@/lib/types";

// XHR 只负责文件字节进度；业务状态始终以服务端结果为准。
export async function putFile(
  upload: Upload,
  file: File,
  onProgress: (value: number) => void,
) {
  let csrf: string | undefined;
  if (upload.url.startsWith("/"))
    csrf = (await api<{ token: string }>("/auth/csrf")).token;
  return new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", upload.url);
    xhr.withCredentials = upload.url.startsWith("/");
    Object.entries(upload.headers ?? {}).forEach(([key, value]) =>
      xhr.setRequestHeader(key, value),
    );
    if (csrf) xhr.setRequestHeader("X-CSRF-Token", csrf);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable)
        onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new Error(`文件上传失败（${xhr.status}），请重试。`));
    xhr.onerror = () => reject(new Error("文件上传连接中断，请重试。"));
    xhr.send(file);
  });
}
