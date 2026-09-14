import { Dataset } from "../api";

export function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

export function formatMetric(value: unknown): string {
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(4);
  }
  if (typeof value === "string" || typeof value === "boolean") {
    return String(value);
  }
  return "—";
}

export function humanize(value: string): string {
  return value.replace(/_/g, " ");
}

export function shortId(value: string): string {
  return value.slice(0, 8);
}

export function fileNameFromReference(reference: string): string {
  const segments = reference.split("/").filter((segment) => segment.length > 0);
  return segments[segments.length - 1] ?? reference;
}

export function datasetOptionLabel(dataset: Dataset): string {
  return `${fileNameFromReference(dataset.object_reference)} · ${shortId(dataset.id)} · ${
    dataset.storage_kind
  }`;
}
