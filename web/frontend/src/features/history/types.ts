import type { components } from "../../../../contracts/generated/api";
// 历史只包含受控元数据，类型直接复用生成契约。
export type HistoryEntry = components["schemas"]["HistoryEntry"];
export type HistoryKind = HistoryEntry["kind"];
