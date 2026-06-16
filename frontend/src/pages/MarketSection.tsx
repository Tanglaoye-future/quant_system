import type { MarketGroup, QuantData, ZhuangData, OptionsData, CBData } from '../types';
import StrategyCard from '../components/StrategyCard';

interface Props {
  market: MarketGroup;
  showAll?: boolean;
  quantData?: QuantData;
  zhuangData?: ZhuangData;
  optionsData?: OptionsData;
  cbData?: CBData | null;
}

/** 将 strategy_name 映射到 QuantData 的 _source label，用于数据匹配 */
export default function MarketSection({ market, showAll = true, quantData, zhuangData, optionsData, cbData }: Props) {
  const activeCells = market.cells.filter(c => c.status === 'active' && c.has_data);
  const otherCells = market.cells.filter(c => !(c.status === 'active' && c.has_data));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {activeCells.map(cell => (
        <StrategyCard
          key={`${cell.strategy_name}@${cell.market_name}`}
          cell={cell}
          quantData={quantData}
          zhuangData={zhuangData}
          optionsData={optionsData}
          cbData={cbData ?? undefined}
        />
      ))}

      {showAll && otherCells.length > 0 && (
        <>
          <div style={{
            fontSize: 12, fontWeight: 600, color: 'var(--color-text-secondary)',
            textTransform: 'uppercase', letterSpacing: '.5px',
            paddingTop: 8, borderTop: '1px solid var(--color-border)',
          }}>
            {otherCells.length} 个其他组合
          </div>
          {otherCells.map(cell => (
            <StrategyCard
              key={`${cell.strategy_name}@${cell.market_name}`}
              cell={cell}
              quantData={quantData}
              zhuangData={zhuangData}
              optionsData={optionsData}
            />
          ))}
        </>
      )}
    </div>
  );
}
