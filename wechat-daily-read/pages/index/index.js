const apiService = require('../../utils/api');
const testConfig = require('../../config/test');
const { throttle } = require('../../utils/performance');

Page({
  data: {
    todayArticles: [],
    displayArticles: [],
    isLoading: false,
    summaryText: '',
    audioState: 'idle', // idle, playing, paused
    currentDate: '',
    currentScenario: 'normal',
    testMode: testConfig.isTestMode,
    readCount: 0,
    unreadCount: 0,
    showBackTop: false,
    pageReady: false,
    sortBy: 'time', // time, readCount
    currentPage: 1,
    pageSize: 15,
    filterType: 'all', // all, read, unread
    totalPages: 1
  },

  onLoad() {
    this.loadTodayArticles();
    this.setData({
      currentDate: this.formatDate(new Date()),
      currentScenario: apiService.getCurrentScenario()
    });
  },

  onShow() {
    // 每次显示页面刷新数据
    this.loadTodayArticles();
  },

  onReady() {
    // 页面渲染完成后触发动画
    setTimeout(() => {
      this.setData({ pageReady: true });
    }, 50);
  },

  // 下拉刷新
  onPullDownRefresh() {
    this.loadTodayArticles().then(() => {
      wx.stopPullDownRefresh();
      wx.showToast({
        title: '刷新成功',
        icon: 'success',
        duration: 1500
      });
    }).catch(() => {
      wx.stopPullDownRefresh();
    });
  },

  // 监听页面滚动（节流优化）
  onPageScroll: throttle(function(e) {
    const showBackTop = e.scrollTop > 800;
    if (showBackTop !== this.data.showBackTop) {
      this.setData({ showBackTop });
    }
  }, 200),

  // 回到顶部
  scrollToTop() {
    wx.pageScrollTo({
      scrollTop: 0,
      duration: 300
    });
  },

  goToManage() {
    wx.switchTab({
      url: '/pages/manage/manage'
    });
  },

  async loadTodayArticles() {
    this.setData({ isLoading: true });

    try {
      // 使用API服务获取今日文章
      const res = await apiService.request({
        name: 'getDailyArticles',
        data: {
          date: this.formatDate(new Date())
        }
      });

      if (res.success) {
        const articles = res.articles || [];
        const readCount = articles.filter(item => item.hasRead).length;
        const unreadCount = articles.filter(item => !item.hasRead).length;

        this.setData({
          todayArticles: articles,
          summaryText: res.summary || '暂无汇总信息',
          readCount: readCount,
          unreadCount: unreadCount,
          currentPage: 1
        });

        // 重新计算显示的文章
        this.updateDisplayArticles();

        // 如果是测试模式，显示场景信息
        if (this.data.testMode && testConfig.currentScenario !== 'normal') {
          wx.showToast({
            title: `测试模式: ${testConfig.currentScenario}`,
            icon: 'none',
            duration: 2000
          });
        }
      } else {
        // 处理错误
        this.handleError('获取文章失败', res.error);
      }
    } catch (error) {
      console.error('获取文章失败:', error);
      this.handleError('获取文章失败', error.message);
    } finally {
      this.setData({ isLoading: false });
    }
  },

  async generateSummary() {
    wx.showLoading({ title: '生成汇总中...' });

    try {
      const res = await apiService.request({
        name: 'generateSummary',
        data: {
          articles: this.data.todayArticles
        }
      });

      if (res.success) {
        this.setData({
          summaryText: res.summary
        });
      } else {
        this.handleError('生成汇总失败', res.error);
      }
    } catch (error) {
      console.error('生成汇总失败:', error);
      this.handleError('生成汇总失败', error.message);
    } finally {
      wx.hideLoading();
    }
  },

  async playAudio() {
    const { audioState, summaryText } = this.data;

    if (audioState === 'playing') {
      // 暂停播放
      wx.pauseBackgroundAudio();
      this.setData({ audioState: 'paused' });
      return;
    }

    if (audioState === 'paused') {
      // 继续播放
      wx.resumeBackgroundAudio();
      this.setData({ audioState: 'playing' });
      return;
    }

    // idle 状态 - 开始播放
    if (!summaryText || summaryText === '暂无汇总信息') {
      wx.showToast({
        title: '没有可播报的内容',
        icon: 'none'
      });
      return;
    }

    wx.showLoading({ title: '生成语音中...' });

    try {
      // 调用文字转语音API
      const res = await apiService.request({
        name: 'textToSpeech',
        data: {
          text: summaryText
        }
      });

      if (res.success) {
        wx.hideLoading();

        // 在测试模式下，模拟播放
        if (this.data.testMode) {
          this.setData({ audioState: 'playing' });
          wx.showToast({
            title: '语音播放中（测试模式）',
            icon: 'success',
            duration: 2000
          });

          // 模拟10秒播放，然后停止
          this.audioPlayTimer = setTimeout(() => {
            this.setData({ audioState: 'idle' });
          }, 10000);
        } else {
          // 真实播放
          wx.playBackgroundAudio({
            dataUrl: res.audioUrl,
            title: '今日汇总播报',
            success: () => {
              this.setData({ audioState: 'playing' });
            },
            fail: (error) => {
              this.handleError('播放失败', '音频播放失败，请重试');
            }
          });
        }
      } else {
        wx.hideLoading();
        this.handleError('语音生成失败', res.error);
      }
    } catch (error) {
      wx.hideLoading();
      console.error('语音播报失败:', error);
      this.handleError('语音播报失败', error.message);
    }
  },

  stopAudio() {
    wx.stopBackgroundAudio();
    if (this.audioPlayTimer) {
      clearTimeout(this.audioPlayTimer);
    }
    this.setData({ audioState: 'idle' });
  },

  onAudioStop() {
    this.setData({ audioState: 'idle' });
  },

  // 更新显示的文章列表
  updateDisplayArticles() {
    let filtered = [...this.data.todayArticles];

    // 1. 根据过滤类型筛选
    if (this.data.filterType === 'read') {
      filtered = filtered.filter(item => item.hasRead);
    } else if (this.data.filterType === 'unread') {
      filtered = filtered.filter(item => !item.hasRead);
    }

    // 2. 根据排序方式排序
    if (this.data.sortBy === 'readCount') {
      filtered = filtered.sort((a, b) => (b.readCount || 0) - (a.readCount || 0));
    } else {
      // 按发布时间排序（默认）
      filtered = filtered.sort((a, b) => new Date(b.publishTime) - new Date(a.publishTime));
    }

    // 3. 计算分页
    const totalPages = Math.ceil(filtered.length / this.data.pageSize);
    const start = (this.data.currentPage - 1) * this.data.pageSize;
    const end = start + this.data.pageSize;
    const displayArticles = filtered.slice(start, end);

    this.setData({
      displayArticles,
      totalPages,
      filteredTotal: filtered.length
    });
  },

  // 切换过滤类型
  onFilterChange(e) {
    const { type } = e.currentTarget.dataset;
    this.setData({
      filterType: type,
      currentPage: 1
    });
    this.updateDisplayArticles();
  },

  // 切换排序方式
  onSortChange(e) {
    const { sort } = e.currentTarget.dataset;
    this.setData({
      sortBy: sort,
      currentPage: 1
    });
    this.updateDisplayArticles();
  },

  // 查看全部文章
  viewAllArticles() {
    wx.navigateTo({
      url: '/pages/report/report'
    });
  },

  viewArticle(e) {
    const { article } = e.currentTarget.dataset;
    if (!article || !article.id) return;
    wx.setStorageSync('selectedArticle', article);
    wx.navigateTo({
      url: `/pages/detail/detail?id=${encodeURIComponent(article.id)}`
    });
  },

  viewReport() {
    wx.navigateTo({
      url: '/pages/report/report'
    });
  },

  formatDate(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  },

  // 统一错误处理
  handleError(title, message) {
    // 根据错误类型显示不同的提示
    const errorMsg = message || '操作失败，请重试';

    if (errorMsg.includes('网络') || errorMsg.includes('连接')) {
      wx.showModal({
        title: title,
        content: errorMsg,
        confirmText: '重试',
        success: (res) => {
          if (res.confirm) {
            // 根据当前操作类型决定重试内容
            if (title === '获取文章失败') {
              this.loadTodayArticles();
            } else if (title === '生成汇总失败') {
              this.generateSummary();
            } else if (title === '语音播报失败') {
              this.playAudio();
            }
          }
        }
      });
    } else {
      wx.showToast({
        title: errorMsg,
        icon: 'none',
        duration: 3000
      });
    }
  },

  // 测试功能：切换场景（仅在测试模式下显示）
  switchTestScenario() {
    if (!this.data.testMode) return;

    const scenarios = ['normal', 'slow', 'error', 'empty'];
    const currentIndex = scenarios.indexOf(testConfig.currentScenario);
    const nextIndex = (currentIndex + 1) % scenarios.length;
    const nextScenario = scenarios[nextIndex];

    apiService.switchScenario(nextScenario);
    this.setData({ currentScenario: nextScenario });

    wx.showActionSheet({
      itemList: [
        `当前: ${nextScenario}`,
        'normal - 正常场景',
        'slow - 网络慢',
        'error - 错误场景',
        'empty - 空数据'
      ],
      success: (res) => {
        if (res.tapIndex > 0) {
          const selectedScenario = scenarios[res.tapIndex - 1];
          apiService.switchScenario(selectedScenario);
          this.setData({ currentScenario: selectedScenario });
          this.loadTodayArticles(); // 重新加载数据
        }
      }
    });
  }
});