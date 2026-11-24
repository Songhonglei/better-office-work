const { wechatArticleUrl } = require('../../utils/wechat-url');

Page({
  data: { url: '' },

  onLoad(options = {}) {
    try {
      this.setData({ url: wechatArticleUrl(decodeURIComponent(options.url || '')) });
    } catch {
      this.setData({ url: '' });
    }
  },

  copyUrl() {
    if (this.data.url) wx.setClipboardData({ data: this.data.url });
  },
});
