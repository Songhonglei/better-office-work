const { throttle } = require('../../utils/performance');

// 提取图片 URL
function extractImages(html) {
  if (!html) return [];

  const imageUrls = [];
  const imgRegex = /<img[^>]+src=["']([^"']+)["'][^>]*>/g;
  let match;

  while ((match = imgRegex.exec(html)) !== null) {
    imageUrls.push({
      src: match[1],
      loaded: false
    });
  }

  return imageUrls;
}

// HTML 转 rich-text 节点
function htmlToRichText(html) {
  if (!html) return [];

  const nodes = [];
  const parser = /(<[^>]+>|[^<]+)/g;
  let match;

  while ((match = parser.exec(html)) !== null) {
    const content = match[0];

    // 处理标签
    if (content.startsWith('<')) {
      const tagMatch = content.match(/<(\w+)([^>]*)>/);
      if (tagMatch) {
        const tagName = tagMatch[1].toLowerCase();
        const attrs = tagMatch[2];

        // 处理 img 标签
        if (tagName === 'img') {
          const srcMatch = attrs.match(/src=["']([^"']+)["']/);
          if (srcMatch) {
            nodes.push({
              name: 'img',
              attrs: {
                src: srcMatch[1],
                style: 'max-width: 100%; height: auto; display: block; margin: 20rpx 0;'
              }
            });
          }
        }
        // 处理其他常见标签
        else if (!content.includes('</') && !content.endsWith('/>')) {
          // 自闭合标签处理
        }
      }
    } else if (content.trim()) {
      // 处理文本内容
      nodes.push({
        type: 'text',
        text: content.trim()
      });
    }
  }

  return nodes;
}

Page({
  data: {
    article: null,
    richTextNodes: [],
    articleImages: [],
    loading: true,
    readProgress: 0,
    isCollected: false,
    collectedArticles: [],
    showBackTop: false
  },

  onLoad(options) {
    const { id } = options;
    this.loadArticleDetail(id);
    this.loadCollectionStatus(id);
  },

  // 加载收藏状态
  loadCollectionStatus(articleId) {
    try {
      const collected = wx.getStorageSync('collectedArticles') || [];
      const isCollected = collected.some(item => item.id === articleId);
      this.setData({ isCollected, collectedArticles: collected });
    } catch (e) {
      console.error('加载收藏状态失败:', e);
    }
  },

  async loadArticleDetail(id) {
    const selected = wx.getStorageSync('selectedArticle');
    const article = selected && selected.id === id ? selected : null;
    if (!article) {
      wx.showToast({ title: '请从文章列表重新打开', icon: 'none' });
      this.setData({ article: null, loading: false });
      return;
    }
    const content = article.content || article.digest || '';
    this.setData({
      article,
      richTextNodes: htmlToRichText(content),
      articleImages: extractImages(content),
      loading: false,
    });
  },

  // 图片加载成功
  onImageLoad(e) {
    const { dataset } = e.currentTarget;
    const index = this.data.articleImages.findIndex(img => img.src === dataset.src);
    if (index !== -1) {
      const images = [...this.data.articleImages];
      images[index].loaded = true;
      this.setData({ articleImages: images });
    }
  },

  // 图片加载失败
  onImageError(e) {
    const { dataset } = e.currentTarget;
    console.warn('图片加载失败:', dataset.src);
  },

  // 预览图片
  previewImage(e) {
    const { src } = e.currentTarget.dataset;
    const urls = this.data.articleImages.map(img => img.src);
    wx.previewImage({
      current: src,
      urls: urls,
      success() {
        console.log('预览成功');
      },
      fail() {
        wx.showToast({
          title: '预览失败',
          icon: 'error'
        });
      }
    });
  },

  // 页面滚动监听（节流优化）
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

  // 记录阅读进度
  onArticleScroll(e) {
    const { scrollTop, scrollHeight } = e.detail;
    const progress = Math.min(
      Math.round((scrollTop / (scrollHeight - e.detail.clientHeight)) * 100),
      100
    );
    this.setData({ readProgress: progress });
  },

  // 切换收藏状态
  toggleCollect() {
    const { article, isCollected, collectedArticles } = this.data;
    if (!article) return;

    try {
      let updated;
      if (isCollected) {
        // 移除收藏
        updated = collectedArticles.filter(item => item.id !== article.id);
        wx.showToast({
          title: '取消收藏',
          icon: 'success',
          duration: 1500
        });
      } else {
        // 添加收藏
        updated = [
          ...collectedArticles,
          {
            id: article.id,
            title: article.title,
            accountName: article.accountName,
            publishTime: article.publishTime,
            collectTime: new Date().toISOString()
          }
        ];
        wx.showToast({
          title: '已收藏',
          icon: 'success',
          duration: 1500
        });
      }

      wx.setStorageSync('collectedArticles', updated);
      this.setData({
        isCollected: !isCollected,
        collectedArticles: updated
      });
    } catch (e) {
      console.error('收藏操作失败:', e);
      wx.showToast({
        title: '操作失败',
        icon: 'error'
      });
    }
  },

  // 复制链接
  copyLink() {
    const { article } = this.data;
    if (!article) return;

    const link = `https://mp.weixin.qq.com/s?__biz=&mid=${article.id}&sn=${article.id}`;

    try {
      wx.setClipboardData({
        data: link,
        success() {
          wx.showToast({
            title: '链接已复制',
            icon: 'success',
            duration: 1500
          });
        },
        fail() {
          wx.showToast({
            title: '复制失败',
            icon: 'error'
          });
        }
      });
    } catch (e) {
      console.error('复制链接失败:', e);
      wx.showToast({
        title: '复制失败',
        icon: 'error'
      });
    }
  },

  onShareAppMessage() {
    return {
      title: this.data.article?.title || '文章分享',
      path: `/pages/detail/detail?id=${this.data.article?.id}`
    };
  }
});