import { useState } from 'react';
import SystemStatusBar from '../components/SystemStatusBar';
import TabNav from '../components/TabNav';
import AShareSection from './AShareSection';
import USSection from './USSection';
import HKSection from './HKSection';
import type { ReportSummary, MarketsResponse } from '../types';

export default function DashboardPage({ data, markets }: { data: ReportSummary; markets: MarketsResponse }) {
  const [activeTab, setActiveTab] = useState('A 股');

  return (
    <>
      <SystemStatusBar markets={markets} />

      <TabNav active={activeTab} onChange={setActiveTab} />

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
