const apiService = require('../../utils/api');
const { throttle } = require('../../utils/performance');

Page({
  data: {
    reportData: null,
    loading: true,
    currentDate: '',
    showBackTop: false
  },

  onLoad() {
    const date = new Date();
    this.setData({
      currentDate: this.formatDate(date)
    });
    this.loadReport();
  },

  async loadReport() {
    try {
      const res = await apiService.request({
        name: 'getDailyArticles',
        data: { date: this.data.currentDate }
      });

      if (res.success) {
        this.setData({
          reportData: this.generateReport(res.articles || []),
          loading: false
        });
      }
    } catch (error) {
      console.error('加载报告失败:', error);
      this.setData({ loading: false });
    }
  },

  generateReport(articles) {
    // 按分类统计
    const categories = {};
    articles.forEach(article => {
      if (!categories[article.category]) {
        categories[article.category] = {
          count: 0,
          articles: [],
          totalRead: 0
        };
      }
      categories[article.category].count++;
      categories[article.category].articles.push(article);
      categories[article.category].totalRead += article.readCount || 0;
    });

    // 生成报告
    return {
      total: articles.length,
      categories: categories,
      topArticles: articles
        .sort((a, b) => (b.readCount || 0) - (a.readCount || 0))
        .slice(0, 10)
    };
  },

  formatDate(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  },

  onPageScroll: throttle(function(e) {
    const showBackTop = e.scrollTop > 800;
    if (showBackTop !== this.data.showBackTop) {
      this.setData({ showBackTop });
    }
  }, 200),

  scrollToTop() {
    wx.pageScrollTo({
      scrollTop: 0,
      duration: 300
    });
  },

  onShareAppMessage() {
    return {
      title: `${this.data.currentDate} 公众号汇总报告`,
      path: '/pages/report/report'
    };
  }
});