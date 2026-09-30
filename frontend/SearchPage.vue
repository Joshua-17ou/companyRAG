<template>
  <div class="container">
    <div class="header">
      <h1>🏥 医院SPD规则库</h1>
      <p>企业级医疗供应链智能搜索系统</p>
    </div>

    <div class="search-box">
      <input
        type="text"
        placeholder="例如：中山三院标签打印、出库单要求、发票流程..."
        v-model="query"
        @keyup.enter="performSearch"
        :disabled="loading"
      />
      <button @click="performSearch" :disabled="loading">
        {{ loading ? '🔍 搜索中...' : '🔍 搜索' }}
      </button>
    </div>

    <div v-if="error" class="error-message">
      <strong>❌ 错误：</strong> {{ error }}
    </div>

    <div v-if="stats" class="stats">
      <div class="stat-item">
        <span class="stat-label">查询词：</span>
        <span class="stat-value">{{ stats.query }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">找到结果：</span>
        <span class="stat-value">{{ stats.count }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">搜索耗时：</span>
        <span class="stat-value">{{ stats.time }}s</span>
      </div>
    </div>

    <div v-if="loading" class="loading">
      <div class="spinner"></div>
      <p>正在搜索规则库...</p>
    </div>

    <div v-else-if="results.length === 0 && stats" class="empty-state">
      <div class="empty-icon">🔎</div>
      <h3>没有找到匹配的结果</h3>
      <p>尝试更改搜索条件</p>
    </div>

    <div v-else-if="results.length === 0 && !stats" class="empty-state">
      <div class="empty-icon">🔎</div>
      <h3>还没有搜索结果</h3>
      <p>输入关键词开始搜索医院规则库</p>
    </div>

    <div v-else class="results">
      <ResultCard
        v-for="result in results"
        :key="result.rank"
        :result="result"
      />
    </div>
  </div>
</template>

<script>
import ResultCard from './ResultCard.vue';

const API_BASE = 'http://localhost:8000/api';

export default {
  name: 'SearchPage',
  components: {
    ResultCard
  },
  data() {
    return {
      query: '',
      results: [],
      loading: false,
      error: '',
      stats: null
    };
  },
  methods: {
    async performSearch() {
      if (!this.query.trim()) {
        this.error = '请输入搜索词';
        return;
      }

      this.loading = true;
      this.error = '';
      const startTime = Date.now();

      try {
        const response = await fetch(
          `${API_BASE}/search?query=${encodeURIComponent(this.query)}&top_k=5`,
          { method: 'POST' }
        );

        const data = await response.json();
        const elapsed = ((Date.now() - startTime) / 1000).toFixed(2);

        if (data.status !== 'success') {
          this.error = data.detail || '搜索失败';
          this.results = [];
          return;
        }

        this.results = data.results || [];
        this.stats = {
          query: this.query,
          count: this.results.length,
          time: elapsed
        };
      } catch (err) {
        this.error = `搜索出错：${err.message}`;
        this.results = [];
      } finally {
        this.loading = false;
      }
    }
  }
};
</script>

<style scoped>
/* ... 复用HTML版本的CSS ... */
</style>
