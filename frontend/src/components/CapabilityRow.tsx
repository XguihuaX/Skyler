/**
 * UX-002 — 通用 capability accordion row。
 *
 * 跟 ExtensionsSection 的 ClientRow/ToolList 平行（但**不**复用——它们是
 * MCP-specific，server/tool 两层关系）。CapabilityRow 单层 accordion：
 *
 *   折叠态：[caret] [leftIcon?] displayName [statusBadge?]
 *           briefDescription (小灰字)
 *
 *   展开态：折叠态全部 + 下方 expandedContent（caller 自己填）
 *
 * 视觉对齐 UX-001 ClientRow（同 padding / caret / 字号）。`ChevronDown` /
 * `ChevronRight` 跟 UX-001 / hotfix-6 一致。
 */
import { useState, type ReactNode } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';


export interface CapabilityRowProps {
  /** capability 唯一标识符（用于 React key / aria-label 等）。 */
  name: string;
  /** 显示名（如 "今日日程"，"读取 Word 文档"）。 */
  displayName: string;
  /** 折叠态显示的简短描述（< 60 字推荐；caller 自己 trim）。 */
  briefDescription: string;
  /** 折叠态右侧状态区（健康灯 + 文字 + ext 角标等，caller 自定义）。 */
  statusBadge?: ReactNode;
  /** 折叠态最左侧的 icon（CapabilityIcon 等）。 */
  leftIcon?: ReactNode;
  /** 展开后渲染的完整内容（description 整段 + 谁能调 + 触发 + 等）。 */
  expandedContent: ReactNode;
  /** 默认是否展开，默认 false（**全折叠**——UX-002 硬约束）。 */
  defaultExpanded?: boolean;
}


export default function CapabilityRow({
  name,
  displayName,
  briefDescription,
  statusBadge,
  leftIcon,
  expandedContent,
  defaultExpanded = false,
}: CapabilityRowProps) {
  const [expanded, setExpanded] = useState<boolean>(defaultExpanded);

  return (
    <div
      className="py-2"
      style={{ borderTop: '1px solid var(--color-border)' }}
      data-capability={name}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="p-0.5 -ml-1 rounded hover:opacity-80"
              aria-label={expanded ? '折叠' : '展开'}
              aria-expanded={expanded}
              style={{ color: 'var(--color-text-secondary)' }}
            >
              {expanded
                ? <ChevronDown size={12} />
                : <ChevronRight size={12} />}
            </button>
            {leftIcon && (
              <span
                className="w-5 h-5 rounded flex items-center justify-center shrink-0"
                style={{
                  background: 'var(--color-bg-elevated)',
                  color: 'var(--color-text-primary)',
                }}
              >
                {leftIcon}
              </span>
            )}
            <span
              className="text-sm font-medium truncate"
              style={{ color: 'var(--color-text-primary)' }}
            >
              {displayName}
            </span>
            {statusBadge && (
              <span className="flex items-center gap-1 ml-auto shrink-0">
                {statusBadge}
              </span>
            )}
          </div>
          {briefDescription && (
            <div
              className="text-xs truncate"
              style={{ color: 'var(--color-text-secondary)', marginLeft: 16 }}
            >
              {briefDescription}
            </div>
          )}
        </div>
      </div>
      {expanded && (
        <div
          className="mt-2"
          style={{
            marginLeft: 16,
            paddingLeft: 8,
            borderLeft: '1px dashed var(--color-border)',
          }}
        >
          {expandedContent}
        </div>
      )}
    </div>
  );
}
