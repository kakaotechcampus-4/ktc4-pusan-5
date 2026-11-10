/**
 * 목업 빌더가 "필요한 필드만 덮어쓰기"를 하도록 돕는다.
 * 객체는 깊게 합치고, 배열·null·원시값은 통째로 바꾼다.
 *   mockStockOverview({ quote: { data: { change: 0 } } })
 */
export type DeepPartial<T> = T extends readonly unknown[]
  ? T
  : T extends object
    ? { [Key in keyof T]?: DeepPartial<T[Key]> }
    : T;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function mergeDeep<T>(base: T, overrides: DeepPartial<T> | undefined): T {
  if (overrides === undefined) return base;
  if (!isPlainObject(base) || !isPlainObject(overrides)) return overrides as T;

  const merged: Record<string, unknown> = { ...base };
  for (const [key, value] of Object.entries(overrides)) {
    if (value === undefined) continue;
    merged[key] = mergeDeep(base[key], value as DeepPartial<unknown>);
  }
  return merged as T;
}
