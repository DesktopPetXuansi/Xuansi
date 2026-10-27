"use client";

import { Button, Heading } from "@/components/ui";
import type { ApiError } from "@/lib/api";
import { useState } from "react";
import { feedbackStatuses } from "./feedback-item";
import { FeedbackList, type FeedbackFilter } from "./feedback-list";
import styles from "./feedback.module.css";

const filters = ["NEW", "IN_PROGRESS", "RESOLVED", "ALL"] as const;

export function FeedbackCenter() {
  const [filter, setFilter] = useState<FeedbackFilter>("NEW");
  const [working, setWorking] = useState(false);
  const [accessError, setAccessError] = useState<ApiError>();
  return (
    <>
      <Heading title="反馈中心">
        直接查看并回复反馈。私有对话不会公开到 GitHub；只标记状态不会发送回复。
      </Heading>
      <div className={styles.toolbar}>
        <div className={styles.filters} role="group" aria-label="处理状态">
          {filters.map((value) => (
            <Button
              key={value}
              className={filter === value ? "" : "secondary"}
              aria-pressed={filter === value}
              disabled={working}
              onClick={() => {
                if (filter === value) return;
                setFilter(value);
                console.debug("[反馈中心] 切换处理状态筛选");
              }}
            >
              {value === "ALL" ? "全部" : feedbackStatuses[value]}
            </Button>
          ))}
        </div>
      </div>
      {/* 筛选重建列表，旧筛选请求即使迟到也不会覆盖新筛选。 */}
      <FeedbackList
        key={filter}
        filter={filter}
        accessError={accessError}
        onAccessError={setAccessError}
        onWorkingChange={setWorking}
      />
    </>
  );
}
