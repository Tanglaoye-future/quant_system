import useReportData from './hooks/useReportData';
import Layout from './components/Layout';
import DashboardPage from './pages/DashboardPage';

export default function App() {
  const { data, loading, error, updatedAt, refresh } = useReportData();
  const date = data?.quant?.date || data?.options?.date || data?.zhuang?.date || '';

  return (
    <Layout date={date} updatedAt={updatedAt} onRefresh={refresh} loading={loading}>
      {error && (
        <div className="mb-8 p-4 bg-[#ffe8e6] border border-[#ff453a]/20 rounded-2xl text-sm text-[#c0392b]">
          无法加载数据：{error}
          <button onClick={refresh} className="ml-3 underline font-medium">
            重试
          </button>
        </div>
      )}

      {loading && !data && (
        <div className="flex items-center justify-center py-24">
          <div className="text-sm text-[#aeaeb2]">加载中…</div>
        </div>
      )}

      {data && <DashboardPage data={data} />}
    </Layout>
  );
}
