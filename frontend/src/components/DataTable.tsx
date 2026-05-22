import type { ColumnDef } from '../types';

export type Column<T> = ColumnDef<T>;

export default function DataTable<T>({
  columns,
  data,
  emptyText = '暂无数据',
}: {
  columns: Column<T>[];
  data: T[];
  emptyText?: string;
}) {
  if (data.length === 0) {
    return (
      <div className="text-center py-10 text-[#aeaeb2] text-sm">{emptyText}</div>
    );
  }
  return (
    <div className="overflow-x-auto -mx-2">
      <table>
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key} className={col.className}>
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, i) => (
            <tr key={i}>
              {columns.map((col) => (
                <td key={col.key} className={col.className}>
                  {col.render(row, i)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
