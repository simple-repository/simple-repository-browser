const path = require('path');

module.exports = {
  entry: {
    'simple-repository-browser.core.js': './simple-repository-browser.core.js',
    'simple-repository-browser.project.js': './simple-repository-browser.project.js',
  },
  output: {
    filename: '[name]',
    path: path.resolve(__dirname, '../simple_repository_browser/static/js/')
  },
  resolve: {
    extensions: [".ts", ".js"],
  },
  module: {
    rules: [
      {
        test: /\.(scss)$/,
        use: [
          {
            // Adds CSS to the DOM by injecting a `<style>` tag
            loader: 'style-loader'
          },
          {
            // Interprets `@import` and `url()` like `import/require()` and will resolve them
            loader: 'css-loader'
          },
          {
            // Loader for webpack to process CSS with PostCSS
            loader: 'postcss-loader',
            options: {
              postcssOptions: {
                plugins: [
                  [
                    "autoprefixer",
                    {
                    },
                  ],
                ],
              },
            },
          },
          {
            // Loads a SASS/SCSS file and compiles it to CSS
            loader: 'sass-loader'
          }
        ]
      }
    ]
  }
};
