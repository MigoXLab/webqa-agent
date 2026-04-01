import React, { useState, useRef, useEffect } from 'react';

interface ResolutionSelectorProps {
  selectedResolutions: string[];
  onChange: (resolutions: string[]) => void;
  disabled?: boolean;
  className?: string;
  style?: React.CSSProperties;
}

const RESOLUTIONS = [
  { id: 'default', label: '默认分辨率', value: '' },
  { id: '2560x1440', label: '2560 × 1440', value: '2560x1440' },
  { id: '1280x720', label: '1280 × 720', value: '1280x720' },
];

export function ResolutionSelector({ selectedResolutions = [], onChange, disabled, className, style }: ResolutionSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const toggleResolution = (value: string) => {
    if (selectedResolutions.includes(value)) {
      onChange(selectedResolutions.filter(r => r !== value));
    } else {
      onChange([...selectedResolutions, value]);
    }
  };

  const getDisplayText = () => {
    if (!selectedResolutions || selectedResolutions.length === 0) return '默认分辨率';
    if (selectedResolutions.length === 1) {
      const res = RESOLUTIONS.find(r => r.value === selectedResolutions[0]);
      return res ? res.label : selectedResolutions[0];
    }
    return `已选 ${selectedResolutions.length} 项`;
  };

  // 提取布局类名应用到外层容器，确保尺寸和原生一致
  const layoutClasses = className?.match(/\b(flex-1|w-\w+|flex-shrink-\d+|max-w-\w+)\b/g)?.join(' ') || 'w-full';
  const styleClasses = className?.replace(/\b(flex-1|w-\w+|flex-shrink-\d+|max-w-\w+)\b/g, '').trim() || 'px-3 py-1.5 border border-blue-200 rounded-lg text-sm bg-blue-50 text-blue-700';

  return (
    <div className={`relative ${layoutClasses}`} ref={containerRef} style={style}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setIsOpen(!isOpen)}
        className={`appearance-none text-left w-full focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100 disabled:border-gray-300 disabled:text-gray-500 disabled:cursor-not-allowed ${styleClasses}`}
        style={{
          backgroundImage: `url("data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 20 20'%3e%3cpath stroke='%236b7280' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='M6 8l4 4 4-4'/%3e%3c/svg%3e")`,
          backgroundPosition: 'right 0.5rem center',
          backgroundRepeat: 'no-repeat',
          backgroundSize: '1.5em 1.5em',
          paddingRight: '2.5rem',
        }}
      >
        <span className="truncate block">{getDisplayText()}</span>
      </button>

      {isOpen && (
        <div className="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-md shadow-lg py-1 text-sm max-h-60 overflow-auto">
          {RESOLUTIONS.map((res) => {
            const isSelected = selectedResolutions.includes(res.value);
            return (
              <div
                key={res.id}
                className={`px-3 py-2 cursor-pointer flex items-center hover:bg-blue-50 ${isSelected ? 'bg-blue-50 text-blue-700' : 'text-gray-700'}`}
                onClick={(e) => {
                  e.stopPropagation();
                  toggleResolution(res.value);
                }}
              >
                <div className={`w-4 h-4 mr-2 border rounded flex items-center justify-center ${isSelected ? 'bg-blue-600 border-blue-600' : 'border-gray-300'}`}>
                  {isSelected && (
                    <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  )}
                </div>
                {res.label}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
