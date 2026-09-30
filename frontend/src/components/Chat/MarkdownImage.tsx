import React from 'react';
import { Image } from 'antd';

export const normalizeImageUrl = (url: string) => {
  if (!url) return '';
  if (url.startsWith('http://') || url.startsWith('https://')) {
    return url;
  }

  const imageName = url.match(/(?:^|\/)(?:api\/)?images\/([^/?#]+)(?:[?#].*)?$/)?.[1];
  if (imageName) {
    return `/api/images/${imageName}`;
  }
  return url.startsWith('/') ? url : `/${url}`;
};

interface MarkdownImageProps {
  src?: string;
  alt?: string;
}

export const MarkdownImage: React.FC<MarkdownImageProps> = ({ src, alt }) => (
  <Image
    src={normalizeImageUrl(src || '')}
    alt={alt || '图片'}
    preview={{ mask: '点击预览' }}
    style={{
      display: 'block',
      maxWidth: '100%',
      maxHeight: 420,
      width: 'auto',
      height: 'auto',
      objectFit: 'contain',
    }}
  />
);
