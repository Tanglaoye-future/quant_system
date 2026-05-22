import { useState } from 'react';
import SystemStatusBar from '../components/SystemStatusBar';
import TabNav from '../components/TabNav';
import QuantSection from './QuantSection';
import OptionsSection from './OptionsSection';
import ZhuangSection from './ZhuangSection';
import type { ReportSummary } from '../types';

export default function DashboardPage({ data }: { data: ReportSummary }) {
  const [activeTab, setActiveTab] = useState('A 股中线');

  return (
    <>
      <SystemStatusBar quant={data.quant} options={data.options} zhuang={data.zhuang} />

      <TabNav active={activeTab} onChange={setActiveTab} />

      <div className={activeTab === 'A 股中线' ? '' : 'hidden'}>
        <QuantSection data={data.quant} />
      </div>
      <div className={activeTab === 'QQQ 期权' ? '' : 'hidden'}>
        <OptionsSection data={data.options} />
      </div>
      <div className={activeTab === '庄股小盘' ? '' : 'hidden'}>
        <ZhuangSection data={data.zhuang} />
      </div>
    </>
  );
}
