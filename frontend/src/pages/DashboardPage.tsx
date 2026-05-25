import { useState } from 'react';
import SystemStatusBar from '../components/SystemStatusBar';
import TabNav from '../components/TabNav';
import MarketSection from './MarketSection';
import AShareSection from './AShareSection';
import USSection from './USSection';
import HKSection from './HKSection';
import type { ReportSummary, MarketsResponse, MatrixResponse } from '../types';

interface Props {
  data: ReportSummary;
  markets: MarketsResponse;
  matrix: MatrixResponse | null;
}

export default function DashboardPage({ data, markets, matrix }: Props) {
  const [activeTab, setActiveTab] = useState('A 股');

  // 优先使用动态 matrix 渲染；无 matrix 时回退旧硬编码渲染
  if (matrix && matrix.markets.length > 0) {
    const activeMarket = matrix.markets.find(m => m.market_label === activeTab);
    return (
      <>
        <SystemStatusBar markets={markets} matrix={matrix} />
        <TabNav
          tabs={matrix.markets.map(m => m.market_label)}
          active={activeTab}
          onChange={setActiveTab}
        />
        {matrix.markets.map(m => (
          <div key={m.market_name} className={activeTab === m.market_label ? '' : 'hidden'}>
            <MarketSection
              market={m}
              showAll={true}
              quantData={data.quant}
              zhuangData={data.zhuang}
              optionsData={data.options}
            />
          </div>
        ))}
      </>
    );
  }

  // 回退: 旧硬编码渲染 (matrix API 未就绪时)
  return (
    <>
      <SystemStatusBar markets={markets} matrix={null} />

      <TabNav tabs={['A 股', '美股', '港股']} active={activeTab} onChange={setActiveTab} />

      <div className={activeTab === 'A 股' ? '' : 'hidden'}>
        <AShareSection quant={data.quant} zhuang={data.zhuang} />
      </div>
      <div className={activeTab === '美股' ? '' : 'hidden'}>
        <USSection data={data.options} />
      </div>
      <div className={activeTab === '港股' ? '' : 'hidden'}>
        <HKSection data={data.quant} />
      </div>
    </>
  );
}
