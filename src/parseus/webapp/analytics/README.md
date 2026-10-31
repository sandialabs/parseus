# Analytics Webpage

This repository contains an analytics webpage designed to facilitate the training and prediction of various analytical models. The interface is organized into three columns, each serving a specific purpose in the analytics workflow.

## Overview of Columns

### 1. Available Analytics

The first column lists the available analytics models. Each model is accompanied by an information button that provides additional details about its functionality and usage. Users can configure certain fields for each model to tailor the analytics to their specific needs. 

Once the desired analytic is selected and configured, users can click the **Train** button to initiate the training process on data located in Malcolm database. Each analytic is designed to query/aggregate elements of information from Malcolm's database.

### 2. Trained Analytics

The middle column displays a list of analytics that have already been trained. This section allows users to easily access previously trained models. 

At the bottom of this column, there is a **Predict** button that enables users to make predictions on new data using the selected trained analytic.

### 3. Results Display

The third column is dedicated to displaying the results of the predictions. It presents the output as a list of JSON objects, allowing users to utilize the results in their applications. These results can then be pushed to the opensearch database

## To-Do

### Improve Results Visualization

Currently, the output of the results is presented as a list of JSON objects. While this format is functional, it is not the most user-friendly or visually appealing way to display the results. 

#### Areas for Improvement:
- **Visual Representation**: Implement visualizations (such as charts, graphs, or tables) to represent the results in a more interpretable fashion. This could help users quickly grasp the insights derived from the analytics.
- **User Interaction**: Consider adding interactive elements that allow users to explore the results further, such as filtering options or drill-down capabilities.
- **Summary Statistics**: Provide summary statistics or key metrics alongside the visualizations to give users a quick overview of the results.