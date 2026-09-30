import React, { useState } from 'react';
import './SearchPage.css';

const API_BASE = 'http://localhost:8000/api';

export function SearchPage() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [stats, setStats] = useState(null);

  const performSearch = async () => {
    if (!query.trim()) {
      setError('请输入搜索词');
      return;
    }

    setLoading(true);
    setError('');
    const startTime = Date.now();

    try {
      const response = await fetch(
        `${API_BASE}/search?query=${encodeURIComponent(query)}&top_k=5`,
        { method: 'POST' }
      );

      const data = await response.json();
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(2);

      if (data.status !== 'success') {
        setError(data.detail || '搜索失败');
        setResults([]);
        return;
      }

      setResults(data.results || []);
      setStats({
        query,
        count: data.results?.length || 0,
        time: elapsed
      });
    } catch (err) {
      setError(`搜索出错：${err.message}`);
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter') {
      performSearch();
    }
  };

  return (
    <div className="container">
      <div className="header">
        <h1>🏥 医院SPD规则库</h1>
        <p>企业级医疗供应链智能搜索系统</p>
      </div>

      <div className="search-box">
        <input
          type="text"
          placeholder="例如：中山三院标签打印、出库单要求、发票流程..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyPress={handleKeyPress}
        />
        <button onClick={performSearch} disabled={loading}>
          {loading ? '🔍 搜索中...' : '🔍 搜索'}
        </button>
      </div>

      {error && (
        <div className="error-message">
          <strong>❌ 错误：</strong> {error}
        </div>
      )}

      {stats && (
        <div className="stats">
          <div className="stat-item">
            <span className="stat-label">查询词：</span>
            <span className="stat-value">{stats.query}</span>
          </div>
          <div className="stat-item">
            <span className="stat-label">找到结果：</span>
            <span className="stat-value">{stats.count}</span>
          </div>
          <div className="stat-item">
            <span className="stat-label">搜索耗时：</span>
            <span className="stat-value">{stats.time}s</span>
          </div>
        </div>
      )}

      {loading && (
        <div className="loading">
          <div className="spinner"></div>
          <p>正在搜索规则库...</p>
        </div>
      )}

      {!loading && results.length === 0 && stats && (
        <div className="empty-state">
          <div className="empty-icon">🔎</div>
          <h3>没有找到匹配的结果</h3>
          <p>尝试更改搜索条件</p>
        </div>
      )}

      {!loading && results.length === 0 && !stats && (
        <div className="empty-state">
          <div className="empty-icon">🔎</div>
          <h3>还没有搜索结果</h3>
          <p>输入关键词开始搜索医院规则库</p>
        </div>
      )}

      <div className="results">
        {results.map((result) => (
          <ResultCard key={result.rank} result={result} />
        ))}
      </div>
    </div>
  );
}

function ResultCard({ result }) {
  return (
    <div className="result-card">
      <div className="result-header">
        <div>
          <h2>{result.hospital}</h2>
          <div className="result-score">相关度: {(result.score * 100).toFixed(1)}%</div>
        </div>
        <div className="result-rank">第 {result.rank} 条</div>
      </div>
      <div className="result-content">
        <div className="result-meta">
          <div className="meta-item">
            <span>📋 文件ID:</span>
            <span className="meta-badge">{result.metadata.file_id.substring(0, 8)}</span>
          </div>
          <div className="meta-item">
            <span>📍 位置:</span>
            <span className="meta-badge">Chunk {result.metadata.chunk_index}</span>
          </div>
        </div>
        <div className="result-text">{result.text}</div>

        {result.images && result.images.length > 0 && (
          <div className="images-section">
            <div className="images-title">🖼️ 相关图片 ({result.images.length})</div>
            <div className="images-grid">
              {result.images.map((img, idx) => (
                <ImageCard key={idx} image={img} hospital={result.hospital} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ImageCard({ image, hospital }) {
  const [imageError, setImageError] = useState(false);

  return (
    <div className="image-card">
      <div className="image-container">
        {!imageError ? (
          <img
            src={image.url}
            alt={hospital}
            onError={() => setImageError(true)}
          />
        ) : (
          <div style={{ padding: '20px', textAlign: 'center', color: '#95a5a6' }}>
            📷 图片加载失败
          </div>
        )}
      </div>
      <div className="image-info">
        <div className="image-hospital">{hospital}</div>
        <div className="image-filename">{image.path}</div>
      </div>
    </div>
  );
}

export default SearchPage;
