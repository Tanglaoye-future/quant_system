const tabs = ['A 股', '美股', '港股'];

export default function TabNav({
  active,
  onChange,
}: {
  active: string;
  onChange: (tab: string) => void;
}) {
  return (
    <div className="flex gap-1 p-1 bg-[#e5e5ea] rounded-xl mb-8 w-fit">
      {tabs.map((tab) => (
        <button
          key={tab}
          onClick={() => onChange(tab)}
          className={`px-5 py-2 text-sm font-medium rounded-lg transition-all duration-200 ${
            active === tab
              ? 'bg-white text-[#1d1d1f] shadow-sm'
              : 'text-[#86868b] hover:text-[#1d1d1f]'
          }`}
        >
          {tab}
        </button>
      ))}
    </div>
  );
}
