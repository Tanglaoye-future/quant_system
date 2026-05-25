import type { MarketGroup } from '../types';
import StrategyCard from '../components/StrategyCard';

interface Props {
  market: MarketGroup;
  /** 如果 true, 也显示非 active 的 cells (默认 true) */
  showAll?: boolean;
}

export default function MarketSection({ market, showAll = true }: Props) {
  const activeCells = market.cells.filter(c => c.status === 'active' && c.has_data);
  const otherCells = market.cells.filter(c => !(c.status === 'active' && c.has_data));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* active strategies first */}
      {activeCells.map(cell => (
        <StrategyCard key={`${cell.strategy_name}@${cell.market_name}`} cell={cell} />
      ))}

      {/* other strategies below */}
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
            <StrategyCard key={`${cell.strategy_name}@${cell.market_name}`} cell={cell} />
          ))}
        </>
      )}
    </div>
  );
}
