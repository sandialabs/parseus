# Modbus Register Analysis Webpage

This repository contains a webpage designed for retrieving Modbus register values and function codes from Malcom's datastore.

## Features

- **Retrieve Modbus Register Values**: The webpage connects to Malcolm's datastore (modbus_detailed.zeek logs) to fetch register values and function codes.
- **Statistical Information**: Provides statistical insights into function codes and register values over time, helping users understand the distribution and frequency of different operations.
- **Line Graph Visualization**: Displays register values over time in an interactive line graph, allowing users to visualize trends and patterns.
- **Exploratory Data Analysis**: Applies HDBSCAN clustering and PCA dimensionality reduction to group similar states of registers, and identify patterns in the data.

## To-Do

### Improve Visualization and Analysis

- **Enhance Graphing Capabilities**: Consider adding more visualization options (e.g., bar charts, scatter plots) to represent different aspects of the data.
- **User Interaction**: Implement interactive features that allow users to select specific registers or time ranges for analysis.
- **Documentation**: Improve the documentation to provide detailed explanations of the statistical methods used and how to interpret the results.