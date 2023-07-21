/*
 * Copyright (C) 2023, CERN
 * This software is distributed under the terms of the MIT
 * licence, copied verbatim in the file "LICENSE".
 * In applying this license, CERN does not waive the privileges and immunities
 * granted to it by virtue of its status as Intergovernmental Organization
 * or submit itself to any jurisdiction.
 */

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
