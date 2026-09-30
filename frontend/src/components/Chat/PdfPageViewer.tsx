import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Empty, Spin, Tag } from 'antd';
import { api } from '../../services/api';
import type { OcrPage } from '../../types';

interface PdfPageViewerProps {
  fileId: string;
  pageNo: number;
  /** 命中文本片段，用于在页面上定位并高亮对应行 */
  highlightText?: string;
  maxHeight?: number;
}

/**
 * 扫描版 PDF 单页查看器。
 *
 * 坐标换算的关键：bbox 存的是**渲染原图**的像素坐标（按入库时的 DPI），
 * 而屏幕上图片被缩放了，所以每个框都要乘 `displayWidth / page.width`。
 * 用 ResizeObserver 跟踪实际显示宽度，窗口缩放时框会跟着走。
 */
export const PdfPageViewer: React.FC<PdfPageViewerProps> = ({
  fileId,
  pageNo,
  highlightText,
  maxHeight = 560,
}) => {
  const [meta, setMeta] = useState<OcrPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [displayWidth, setDisplayWidth] = useState(0);
  const imgRef = useRef<HTMLImageElement | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    setMeta(null);

    api
      .getPdfOcrMeta(fileId)
      .then((data) => {
        if (!alive) return;
        const page = data.pages?.[String(pageNo)];
        if (!page) {
          setError(`第 ${pageNo} 页没有 OCR 结果`);
          return;
        }
        setMeta(page);
      })
      .catch(() => {
        if (alive) setError('OCR 结果加载失败');
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    return () => {
      alive = false;
    };
  }, [fileId, pageNo]);

  // 跟踪图片的实际显示宽度，缩放窗口时高亮框要跟着重新计算
  useEffect(() => {
    const img = imgRef.current;
    if (!img) return;

    const update = () => setDisplayWidth(img.clientWidth);
    update();

    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', update);
      return () => window.removeEventListener('resize', update);
    }
    const observer = new ResizeObserver(update);
    observer.observe(img);
    return () => observer.disconnect();
  }, [meta]);

  // 找出与命中文本重叠最多的 OCR 行——OCR 结果和分块文本不一定逐字相同
  const matchedIndexes = useMemo(() => {
    if (!meta?.lines?.length || !highlightText?.trim()) return new Set<number>();

    const normalize = (s: string) => s.replace(/\s+/g, '');
    const needle = normalize(highlightText);
    if (!needle) return new Set<number>();

    const hits = new Set<number>();
    meta.lines.forEach((line, idx) => {
      const hay = normalize(line.text || '');
      if (!hay) return;
      // 用短窗口滑一遍，避免整段长文本逐字比对
      const probe = hay.length > 12 ? hay.slice(0, 12) : hay;
      if (needle.includes(probe) || hay.includes(needle.slice(0, 12))) {
        hits.add(idx);
      }
    });
    return hits;
  }, [meta, highlightText]);

  const scale = meta && meta.width > 0 ? displayWidth / meta.width : 0;
  const hasHighlight = matchedIndexes.size > 0;

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 24 }}>
        <Spin tip="正在加载页面…" />
      </div>
    );
  }

  if (error) {
    return <Alert type="warning" showIcon message={error} />;
  }

  if (!meta) {
    return <Empty description="无页面数据" />;
  }

  return (
    <div>
      <div style={{ marginBottom: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
        <Tag color="blue">第 {pageNo} 页</Tag>
        <span style={{ color: '#888', fontSize: 12 }}>
          {meta.width}×{meta.height} @ {meta.dpi}dpi
        </span>
        {hasHighlight && <Tag color="orange">命中 {matchedIndexes.size} 行</Tag>}
      </div>

      <div
        style={{
          position: 'relative',
          display: 'inline-block',
          maxWidth: '100%',
          border: '1px solid #eee',
          borderRadius: 4,
          overflow: 'hidden',
        }}
      >
        <img
          ref={imgRef}
          src={api.pdfPageUrl(fileId, pageNo)}
          alt={`第 ${pageNo} 页`}
          style={{
            display: 'block',
            maxWidth: '100%',
            maxHeight,
            width: 'auto',
            height: 'auto',
          }}
          onLoad={() => {
            if (imgRef.current) setDisplayWidth(imgRef.current.clientWidth);
          }}
        />

        {/* 缩放还没算出来之前不画框，否则会闪一下位置错误的框 */}
        {scale > 0 &&
          meta.lines.map((line, idx) => {
            const [x0, y0, x1, y1] = line.bbox;
            const hit = matchedIndexes.has(idx);
            return (
              <div
                key={idx}
                title={line.text}
                style={{
                  position: 'absolute',
                  left: x0 * scale,
                  top: y0 * scale,
                  width: Math.max((x1 - x0) * scale, 1),
                  height: Math.max((y1 - y0) * scale, 1),
                  background: hit ? 'rgba(255, 165, 0, 0.35)' : 'transparent',
                  border: hit ? '1px solid rgba(255, 140, 0, 0.9)' : '1px solid transparent',
                  pointerEvents: 'none',
                  boxSizing: 'border-box',
                }}
              />
            );
          })}
      </div>
    </div>
  );
};

export default PdfPageViewer;
