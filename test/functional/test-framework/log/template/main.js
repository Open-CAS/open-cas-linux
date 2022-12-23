/*
    Copyright(c) 2019-2021 Intel Corporation
    SPDX-License-Identifier: BSD-3-Clause
*/

function onLoadDocument() {
    hideDebug();
}

function selectMode() {
    var selector = document.getElementById('mode-selector');
    if (selector.value.includes('info')) {
        hideDebug();
    } else {
        showDebug();
    }
}

function hideDebug() {
    var debugTestStepArray = document.getElementsByTagName('li');
    for (i = 0; i < debugTestStepArray.length; i ++) {
        if(debugTestStepArray[i].className.includes('debug')) {
            debugTestStepArray[i].style.display = 'none';
        }
    }
}

function showDebug() {
    var debugTestStepArray = document.getElementsByTagName('li');
    for (i = 0; i < debugTestStepArray.length; i ++) {
        if(debugTestStepArray[i].className.includes('debug')) {
            debugTestStepArray[i].style.display = '';
        }
    }
}

function sidebarCtrl(ctrlHideId, ctrlShowClass) {
    var metaContainer = document.getElementsByClassName("meta-container")[0];
    var sidebar = document.getElementsByClassName('sidebar')[0];
    var sidebarTest = document.getElementById('sidebar-test');
    var ctrlHide = document.getElementById(ctrlHideId);
    var ctrlShowSet = document.getElementsByClassName(ctrlShowClass);
    
    if(sidebar.style.width.includes('15px')) {
        showSidebar(metaContainer, sidebar, ctrlHide, ctrlShowSet, sidebarTest);
    } else {
        hideSidebar(metaContainer, sidebar, ctrlHide, ctrlShowSet, sidebarTest);
    }
}

function showSidebar(mContainer, sidebar, ctrlHide, ctrlShowSet, sidebarTest) {
    sidebar.style.cursor = 'default';
    mContainer.style.marginLeft = '';
    sidebarTest.style.width = '';
    sidebarTest.style.height = '';
    sidebar.style.height = '';
    sidebar.style.marginLeft = '';
    sidebar.style.width = '';
    var i;
    for (i = 0; i < sidebarTest.children.length; i++) { 
        sidebarTest.children[i].style.display = '';
    }
    document.getElementById('iteration-selector').style.display = '';
    document.getElementById('sidebar-iteration-list').style.display = '';
    document.getElementById('sidebar-copyright').style.display = '';
    for(i = 0; i < ctrlShowSet.length; i ++) {
        ctrlShowSet[i].style.display = 'none';
    }
}

function hideSidebar(mContainer, sidebar, ctrlHide, ctrlShowSet, sidebarTest) {
    document.getElementById('iteration-selector').style.display = 'none';
    document.getElementById('sidebar-iteration-list').style.display = 'none';
    document.getElementById('sidebar-copyright').style.display = 'none';
    var i;
    for (i = 0; i < sidebarTest.children.length; i++) { 
        sidebarTest.children[i].style.display = 'none';
    }
    sidebarTest.style.display = '';
    for(i = 0; i < ctrlShowSet.length; i ++) {
        ctrlShowSet[i].style.display = '';
        ctrlShowSet[i].style.color = 'black';
    }
    sidebar.style.width = '15px';
    sidebar.style.marginLeft = '-15px';
    sidebar.style.height = '100%';
    sidebarTest.style.height = '100%';
    sidebarTest.style.width = '100%';
    mContainer.style.marginLeft = '16px';
    sidebar.style.cursor = 'pointer';
}

function previousError() {
    var errorSelector = document.getElementById("error-list-selector");
    if (errorSelector.length > 1) {
        var id = errorSelector.selectedIndex;
        if (id - 1 > 0) {
            errorSelector.selectedIndex = (id - 1);
        } else {
            errorSelector.selectedIndex = (errorSelector.length - 1);
        }
        errorSelected('error-list-selector');
    }
}

function nextError() {
    var errorSelector = document.getElementById("error-list-selector");
    if (errorSelector.length > 1) {
        var id = errorSelector.selectedIndex;
        if (id + 1 < errorSelector.length) {
            errorSelector.selectedIndex = (id + 1);
        } else {
            errorSelector.selectedIndex = 1;
        }
        errorSelected('error-list-selector');
    }
}

function selectIterationFromSelect() {
    var element = document.getElementById("sidebar-iteration-list");
    loadDocument(element.value);
    updateIterationSelector(element);
}

function clickSelectIteration() {
    var element = document.getElementById("sidebar-iteration-list");
    for (i = 0; i < element.length; i ++) {
        option = element[i];
        var cls = option.getAttribute('class');
        switch(cls) {
            case "warning":
                option.style.backgroundColor = "yellow";
                option.style.color = "black";
                break;
            case "skip":
                option.style.backgroundColor = "silver";
                option.style.color = "black";
                break;
            case "fail":
                option.style.backgroundColor = "red";
                option.style.color = "white";
                break;
            case "exception":
                option.style.backgroundColor = "blueviolet";
                option.style.color = "white";
                break;
            default:
                option.style.backgroundColor = "white";
                option.style.color = "black";
                break;
        }
        
    };
}

function selectIteration(iteration) {
    var selectElement = document.getElementById("sidebar-iteration-list");
    var docId = loadDocument(iteration);
    selectElement.selectedIndex = docId;
    updateIterationSelector(selectElement);
}

function loadDocument(fileId) {
    var result = 0;
    if(fileId == 'M') {
        document.getElementById("main-view").src = "iterations/setup.html";
    } else {
        var id = pad(fileId, 3);
        document.getElementById("main-view").src = "iterations/iteration_" + id + ".html";
        result = parseInt(fileId);
    }
    return result;
}

function updateIterationSelector(element) {
    var index = element.selectedIndex
    var option_class = element[index].getAttribute('class')
    if (option_class != null) {
        element.setAttribute('class', "sidebar-iteration-list " + option_class);
    } else {
        element.setAttribute('class', "sidebar-iteration-list");
    }
}

function errorSelected(selectorId) {
    var newLocation = document.getElementById(selectorId).value;
    window.location.hash = newLocation;
}

function pad(strNumber, padding) {
    while((strNumber.length + 1) <= padding) {
        strNumber = "0" + strNumber;
    }
    return strNumber;
}

function showHide(id) {
    var ulElement = document.getElementById(id);
    if(ulElement.style.display == 'none') {
        ulElement.style.display = '';
    } else {
        ulElement.style.display = 'none';
    }
}

function chapterClick(id) {
    var id_array = id.split('.');
    var node_id = "";
    var i = 0;
    var destinationElement = document.getElementById(id);
    if (destinationElement.style.display == 'none') {
        do {
            node_id += id_array[i];
            var ele = document.getElementById(node_id);
            ele.style.display = '';
            node_id += '.';
            i += 1;
        } while (i < id_array.length);
        window.location = '#' + id;
    } else {
        destinationElement.style.display = 'none';
    }
}
