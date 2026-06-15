import { useState } from 'react';
import SystemStatusBar from '../components/SystemStatusBar';
import TradeActionsBar from '../components/TradeActionsBar';
import TSignalCard from '../components/TSignalCard';
import TabNav from '../components/TabNav';
import MarketSection from './MarketSection';
import AShareSection from './AShareSection';
import USSection from './USSection';
import HKSection from './HKSection';
import PanicSection from './PanicSection';
import type { ReportSummary, MarketsResponse, MatrixResponse, PanicData, TSignalsPayload } from '../types';

interface Props {
  data: ReportSummary;
  markets: MarketsResponse;
  matrix: MatrixResponse | null;
  panicData: PanicData | null;
  tSignals: TSignalsPayload | null;
}

export default function DashboardPage({ data, markets, matrix, panicData, tSignals }: Props) {
  const [activeTab, setActiveTab] = useState('A 股');
  const hasTSignals = tSignals && (tSignals.today.length > 0 || tSignals.history.length > 0);

  const panicLabel = 'Panic';

  // 优先使用动态 matrix 渲染；无 matrix 时回退旧硬编码渲染
  if (matrix && matrix.markets.length > 0) {
    const tabLabels = [...matrix.markets.map(m => m.market_label), panicLabel];
    return (
      <>
        <SystemStatusBar markets={markets} matrix={matrix} />
        <TradeActionsBar data={data} />
        {hasTSignals && (
          <div className="mb-6"><TSignalCard data={tSignals} /></div>
        )}
        <TabNav tabs={tabLabels} active={activeTab} onChange={setActiveTab} />
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
        <div className={activeTab === panicLabel ? '' : 'hidden'}>
          {panicData && <PanicSection data={panicData} />}
        </div>
      </>
    );
  }

  // 回退: 旧硬编码渲染 (matrix API 未就绪时)
  return (
    <>
      <SystemStatusBar markets={markets} matrix={null} />
      <TradeActionsBar data={data} />
      {hasTSignals && (
        <div className="mb-6"><TSignalCard data={tSignals} /></div>
      )}

      <TabNav tabs={['A 股', '美股', '港股', panicLabel]} active={activeTab} onChange={setActiveTab} />

      <div className={activeTab === 'A 股' ? '' : 'hidden'}>
        <AShareSection quant={data.quant} zhuang={data.zhuang} />
      </div>
      <div className={activeTab === '美股' ? '' : 'hidden'}>
        <USSection data={data.options} />
      </div>
      <div className={activeTab === '港股' ? '' : 'hidden'}>
        <HKSection data={data.quant} />
      </div>
      <div className={activeTab === panicLabel ? '' : 'hidden'}>
        {panicData && <PanicSection data={panicData} />}
      </div>
    </>
  );
}
