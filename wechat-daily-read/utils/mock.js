// Mock数据生成工具
const mockData = {
  // Mock公众号列表
  accounts: [
    {
      _id: 'account_001',
      name: '科技前沿',
      biz: 'demo_120',
      category: '科技',
      isActive: true,
      autoAdded: true,
      createTime: '2025-01-01',
      lastVisitTime: '2025-01-08',
      visitCount: 15,
      description: '专注于最新科技资讯和前沿技术分析'
    },
    {
      _id: 'account_002',
      name: '财经头条',
      biz: 'demo_404',
      category: '财经',
      isActive: true,
      autoAdded: false,
      createTime: '2025-01-02',
      lastVisitTime: '2025-01-08',
      visitCount: 8,
      description: '提供专业财经新闻和投资建议'
    },
    {
      _id: 'account_003',
      name: '生活美学',
      biz: 'demo_685',
      category: '生活',
      isActive: true,
      autoAdded: true,
      createTime: '2025-01-03',
      lastVisitTime: '2025-01-07',
      visitCount: 12,
      description: '分享高品质生活方式和美学理念'
    },
    {
      _id: 'account_004',
      name: '娱乐圈观察',
      biz: 'demo_968',
      category: '娱乐',
      isActive: false,
      autoAdded: false,
      createTime: '2025-01-01',
      lastVisitTime: '2025-01-05',
      visitCount: 5,
      description: '娱乐圈最新动态和深度报道'
    },
    {
      _id: 'account_005',
      name: '健康养生堂',
      biz: 'demo_1250',
      category: '生活',
      isActive: true,
      autoAdded: true,
      createTime: '2025-01-04',
      lastVisitTime: '2025-01-08',
      visitCount: 20,
      description: '专业健康知识和养生方法分享'
    },
    {
      _id: 'account_006',
      name: 'AI研究院',
      biz: 'demo_1532',
      category: '科技',
      isActive: true,
      autoAdded: true,
      createTime: '2025-01-05',
      lastVisitTime: '2025-01-08',
      visitCount: 18,
      description: '人工智能最新研究和应用案例'
    },
    {
      _id: 'account_007',
      name: '教育新观察',
      biz: 'demo_1814',
      category: '教育',
      isActive: true,
      autoAdded: false,
      createTime: '2025-01-02',
      lastVisitTime: '2025-01-07',
      visitCount: 10,
      description: '教育行业动态和创新教学方法'
    },
    {
      _id: 'account_008',
      name: '美食日记',
      biz: 'demo_2096',
      category: '生活',
      isActive: true,
      autoAdded: true,
      createTime: '2025-01-06',
      lastVisitTime: '2025-01-08',
      visitCount: 25,
      description: '美食制作教程和餐厅推荐'
    },
    {
      _id: 'account_009',
      name: '投资理财圈',
      biz: 'demo_2376',
      category: '财经',
      isActive: false,
      autoAdded: false,
      createTime: '2025-01-03',
      lastVisitTime: '2025-01-04',
      visitCount: 3,
      description: '投资策略和理财知识分享'
    },
    {
      _id: 'account_010',
      name: '体育速报',
      biz: 'demo_2656',
      category: '体育',
      isActive: true,
      autoAdded: true,
      createTime: '2025-01-07',
      lastVisitTime: '2025-01-08',
      visitCount: 7,
      description: '体育赛事直播和体育新闻'
    },
    {
      _id: 'account_011',
      name: '文化长廊',
      biz: 'demo_2934',
      category: '文化',
      isActive: true,
      autoAdded: false,
      createTime: '2025-01-01',
      lastVisitTime: '2025-01-06',
      visitCount: 9,
      description: '传统文化和艺术欣赏'
    },
    {
      _id: 'account_012',
      name: '创业邦',
      biz: 'demo_3210',
      category: '财经',
      isActive: true,
      autoAdded: true,
      createTime: '2025-01-05',
      lastVisitTime: '2025-01-08',
      visitCount: 14,
      description: '创业资讯和商业案例分析'
    }
  ],

  // Mock文章数据
  articles: [],

  // 生成今日文章
  generateTodayArticles() {
    const today = new Date();
    const articles = [];

    this.accounts.filter(acc => acc.isActive).forEach(account => {
      // 每个活跃账号生成1-3篇文章
      const articleCount = Math.floor(Math.random() * 3) + 1;

      for (let i = 0; i < articleCount; i++) {
        articles.push({
          id: `article_${account.biz}_${today.getTime()}_${i}`,
          title: this.generateTitle(account.category),
          accountName: account.name,
          accountBiz: account.biz,
          category: account.category,
          digest: this.generateDigest(account.category),
          thumbUrl: '',
          url: '',
          publishTime: this.generateTime(today),
          readCount: Math.floor(Math.random() * 10000) + 100,
          hasRead: Math.random() > 0.7 // 30%概率已读
        });
      }
    });

    this.articles = articles.sort((a, b) => new Date(b.publishTime) - new Date(a.publishTime));
    return this.articles;
  },

  // 生成文章标题
  generateTitle(category) {
    const titles = {
      科技: [
        'GPT-5即将发布：人工智能将迎来新突破',
        '苹果Vision Pro二代曝光：价格更亲民',
        '量子计算机实现重大技术突破',
        '新能源汽车销量创新高，行业竞争加剧',
        '5G-A商用元年开启，网速提升10倍'
      ],
      财经: [
        'A股今日大涨：沪指突破3000点',
        '央行降准释放流动性，市场反应积极',
        '比特币价格创新高，投资需谨慎',
        '房企融资环境改善，房地产市场企稳',
        '全球经济复苏态势良好，IMF上调增长预期'
      ],
      生活: [
        '冬季养生指南：这几款汤品温暖你',
        '极简生活：如何打造舒适的居家空间',
        '健康早餐搭配，开启元气满满的一天',
        '断舍离：整理房间的实用技巧',
        '冬季护肤攻略：告别干燥起皮'
      ],
      娱乐: [
        '年度大片票房榜出炉，看看哪部夺冠',
        '明星穿搭解析：学起来提升气质',
        '音乐节回归，这些演出不容错过',
        '综艺节目录制现场探秘',
        '电影新片预告，值得期待的大作'
      ],
      教育: [
        '教育改革新政策，家长必读',
        '孩子注意力不集中怎么办？专家支招',
        '高效学习方法推荐，告别死记硬背',
        '早教利弊分析，科学育儿指南',
        '留学申请季：如何准备文书材料'
      ],
      体育: [
        'NBA常规赛精彩瞬间回顾',
        '足球转会最新动态',
        '冬运会即将开幕，中国队备战情况',
        '马拉松赛季来临，参赛指南',
        '健身达人分享：高效燃脂运动'
      ],
      文化: [
        '博物馆新展：感受千年文化魅力',
        '古籍修复：让历史重获新生',
        '传统手工艺的传承与创新',
        '摄影大师镜头下的中国',
        '文学新作推荐：值得一看的好书'
      ]
    };

    const categoryTitles = titles[category] || titles['生活'];
    return categoryTitles[Math.floor(Math.random() * categoryTitles.length)];
  },

  // 生成文章摘要
  generateDigest(category) {
    const digests = {
      科技: '探讨最新科技趋势，分析技术发展对未来的影响...',
      财经: '深度解析财经新闻，提供专业的投资建议...',
      生活: '分享实用的生活技巧，提升生活品质...',
      娱乐: '带来最新娱乐资讯，让生活更有趣...',
      教育: '关注教育话题，助力孩子成长...',
      体育: '报道体育赛事，传递运动精神...',
      文化: '传承文化精髓，感受艺术魅力...'
    };

    return digests[category] || digests['生活'];
  },

  // 生成发布时间
  generateTime(date) {
    const hours = Math.floor(Math.random() * 24);
    const minutes = Math.floor(Math.random() * 60);
    const publishDate = new Date(date);
    publishDate.setHours(hours, minutes, 0, 0);
    return publishDate.toISOString();
  },

  // 获取文章汇总
  async getDailyArticles(date) {
    return new Promise((resolve) => {
      setTimeout(() => {
        const articles = this.generateTodayArticles();
        const summary = this.generateSummary(articles);
        resolve({
          success: true,
          articles,
          summary,
          total: articles.length
        });
      }, 500); // 模拟网络延迟
    });
  },

  // 生成汇总
  generateSummary(articles) {
    if (articles.length === 0) {
      return '今日暂无新文章';
    }

    const categories = {};
    articles.forEach(article => {
      if (!categories[article.category]) {
        categories[article.category] = 0;
      }
      categories[article.category]++;
    });

    let summary = `【智能汇总】\n\n`;
    summary += `今日共收录${articles.length}篇文章，来自${Object.keys(categories).length}个领域。\n\n`;

    for (const [category, count] of Object.entries(categories)) {
      const hotArticles = articles
        .filter(a => a.category === category)
        .sort((a, b) => b.readCount - a.readCount)
        .slice(0, 2);

      summary += `【${category}】 ${count}篇\n`;
      hotArticles.forEach((article, index) => {
        summary += `• ${article.title}\n`;
      });
      summary += '\n';
    }

    summary += `【热点排行】\n`;
    const topArticles = articles
      .sort((a, b) => b.readCount - a.readCount)
      .slice(0, 3);
    topArticles.forEach((article, index) => {
      summary += `${index + 1}. ${article.title}（阅读量：${article.readCount}）\n`;
    });

    return summary;
  },

  // 模拟添加公众号
  async addAccount(url) {
    return new Promise((resolve) => {
      setTimeout(() => {
        // 模拟解析失败的情况
        if (!url.includes('mp.weixin.qq.com')) {
          resolve({
            success: false,
            error: '请输入正确的微信公众号文章链接'
          });
          return;
        }

        if (!url.includes('__biz=')) {
          resolve({
            success: false,
            error: '无法从链接中提取公众号信息'
          });
          return;
        }

        // 检查是否已存在
        const bizMatch = url.match(/__biz=([^&]+)/);
        if (!bizMatch) {
          // URL格式不正确，没有找到biz参数
          resolve({
            success: false,
            error: '无法识别公众号信息，请检查链接格式'
          });
          return;
        }

        const biz = bizMatch[1];
        const existing = this.accounts.find(acc => acc.biz === biz);

        if (existing) {
          resolve({
            success: true,
            isNew: false,
            account: existing,
            message: '公众号已存在'
          });
          return;
        }

        // 创建新账号
        const newAccount = {
          _id: `account_${Date.now()}`,
          name: `新发现公众号_${Date.now().toString().substr(-6)}`,
          biz: biz,
          category: '其他',
          isActive: true,
          autoAdded: true,
          createTime: new Date().toISOString(),
          description: '通过链接自动添加的公众号'
        };

        this.accounts.push(newAccount);

        resolve({
          success: true,
          isNew: true,
          account: newAccount,
          message: '添加成功'
        });
      }, 300);
    });
  },

  // 模拟语音合成
  async textToSpeech(text) {
    return new Promise((resolve) => {
      setTimeout(() => {
        // 模拟成功率80%
        if (Math.random() > 0.2) {
          resolve({
            success: true,
            audioUrl: 'https://res.wx.qq.com/voice/getvoice?mediaid=demo_audio_id'
          });
        } else {
          resolve({
            success: false,
            error: '语音服务暂时不可用，请稍后重试'
          });
        }
      }, 1000);
    });
  },

  // 获取账号列表
  async getAccounts() {
    return new Promise((resolve) => {
      setTimeout(() => {
        resolve({
          success: true,
          data: this.accounts
        });
      }, 200);
    });
  },

  // 切换账号状态
  async toggleAccount(id, isActive) {
    return new Promise((resolve) => {
      setTimeout(() => {
        const account = this.accounts.find(acc => acc._id === id);
        if (account) {
          account.isActive = isActive;
          resolve({
            success: true
          });
        } else {
          resolve({
            success: false,
            error: '账号不存在'
          });
        }
      }, 100);
    });
  },

  // 删除账号
  async deleteAccount(id) {
    return new Promise((resolve) => {
      setTimeout(() => {
        const index = this.accounts.findIndex(acc => acc._id === id);
        if (index > -1) {
          this.accounts.splice(index, 1);
          resolve({
            success: true
          });
        } else {
          resolve({
            success: false,
            error: '账号不存在'
          });
        }
      }, 100);
    });
  }
};

// 导出mock数据
module.exports = mockData;