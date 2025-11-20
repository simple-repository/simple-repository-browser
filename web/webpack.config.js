const path = require('path');

const miniCssExtractPlugin = require('mini-css-extract-plugin')

module.exports = {
  entry: {
    'bootstrap.customized.js': './bootstrap.customized.js',
  },
  output: {
    filename: '[name]',
    path: path.resolve(__dirname, '../simple_repository_browser/static/vendored/')
  },
  resolve: {
    extensions: [".ts", ".js"],
  },
  plugins: [
    new miniCssExtractPlugin()
  ],
  module: {
    rules: [
      {
        test: /\.(scss)$/,
        use: [
          // {
          //   // Adds CSS to the DOM by injecting a `<style>` tag
          //   loader: 'style-loader'
          // },
          {
            // Extracts CSS for each JS file that includes CSS
            loader: miniCssExtractPlugin.loader
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
