"use client";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import styles from "./resource-upload.module.css";

import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { Button, Field, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { kinds, type Resource } from "@/lib/types";
import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";

export function ResourceDetailsForm({
  item,
  verified,
  kind,
  onCreated,
}: {
  item?: Resource;
  verified: boolean;
  kind: string;
  onCreated: (resource: Resource) => void;
}) {
  const cache = useQueryClient();
  const [error, setError] = useState<unknown>();
  const [success, setSuccess] = useState(false);
  const [busy, setBusy] = useState(false);
  const saving = useRef(false);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving.current || !verified) return;
    const values = new FormData(event.currentTarget);
    const body = {
      name: String(values.get("name")),
      description: String(values.get("description")),
      author: String(values.get("author")),
      license: String(values.get("license")),
      source: String(values.get("source")),
      tags: String(values.get("tags"))
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean),
    };
    // 同一次点击只创建一个作品，避免网络较慢时重复提交。
    saving.current = true;
    setBusy(true);
    setError(undefined);
    setSuccess(false);
    try {
      const saved = await api<Resource>(
        item ? `/resources/${item.id}` : "/resources",
        item ? "PATCH" : "POST",
        item ? body : { ...body, kind: String(values.get("kind")) },
      );
      await cache.invalidateQueries({ queryKey: ["resource", item?.id] });
      if (item) {
        setSuccess(true);
        console.debug("[作品上传] 作品资料已保存");
      } else {
        // 创建成功后再进入文件步骤，避免把保存资料误认为文件已上传。
        console.debug("[作品上传] 作品已创建，进入文件上传");
        onCreated(saved);
      }
    } catch (cause) {
      setError(cause);
      console.warn("[作品上传] 作品资料保存失败");
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="panel" key={item?.id ?? "new"}>
      <h2>{item ? "作品资料" : "填写作品资料"}</h2>
      <div className={item ? "grid-two" : undefined}>
        <Field label="作品名称">
          <Input
            name="name"
            required
            maxLength={120}
            defaultValue={item?.name}
          />
        </Field>
        {item ? (
          <Field label="作品类型">
            <Select value={item.kind} disabled>
              <SelectTrigger aria-label="作品类型" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent position="popper">
                {Object.entries(kinds).map(([value, label]) => (
                  <SelectItem value={value} key={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        ) : (
          <input type="hidden" name="kind" value={kind} />
        )}
      </div>
      <Field label="作品介绍（选填）">
        <Textarea name="description" defaultValue={item?.description} />
      </Field>
      <div className="grid-two">
        <Field label="作者" hint="请填写作品的实际作者。">
          <Input name="author" required defaultValue={item?.author} />
        </Field>
        <Field label="使用许可" hint="说明允许的用途和再分发条件。">
          <Input
            name="license"
            required
            defaultValue={item?.license}
            placeholder="例如：仅个人使用，禁止再分发"
          />
        </Field>
      </div>
      <Collapsible className={styles.advanced}>
        <CollapsibleTrigger>来源与标签（选填）</CollapsibleTrigger>
        <CollapsibleContent forceMount className="data-[state=closed]:hidden">
          <Field label="来源链接（选填）">
            <Input type="url" name="source" defaultValue={item?.source} />
          </Field>
          <Field label="标签（选填）" hint="用英文逗号分隔。">
            <Input name="tags" defaultValue={item?.tags.join(", ")} />
          </Field>
        </CollapsibleContent>
      </Collapsible>
      {!item && <p>请确认你有权上传此作品，并填写真实的作者和使用许可。</p>}
      {error !== undefined && <Notice error={error} />}
      {success && <Notice>作品资料已保存。</Notice>}
      <Button type="submit" disabled={busy || !verified}>
        {busy ? "正在保存…" : item ? "保存资料" : "保存资料，选择文件"}
      </Button>
    </form>
  );
}
