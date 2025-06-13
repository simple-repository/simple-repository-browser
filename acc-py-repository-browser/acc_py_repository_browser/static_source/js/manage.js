function show_page(page_class){
    $('a[data-purpose="page-select"]').addClass('btn-link').removeClass('btn-primary')
    $('a[data-purpose="page-select"].' + page_class).addClass('btn-primary').removeClass('btn-link')

    $('div[data-purpose="page-switch"]').addClass('d-none');
    $('#' + page_class + '-page').removeClass('d-none').removeClass('d-none').removeClass('d-none');
}

$('a.releases').click(() => {
    show_page('releases');
    const currentUrlWithoutFragment = window.location.href.split('#')[0];

    history.replaceState({}, 'Releases', currentUrlWithoutFragment + "#releases");
  }
)

$('a.collaborators').click(() => {
    show_page('collaborators');
    const currentUrlWithoutFragment = window.location.href.split('#')[0];

    history.replaceState({}, 'collaborators', currentUrlWithoutFragment + "#collaborators");
  }
)

$('a.not-implemented').click(() => {alert("This feature is not implemented yet!")})
$('button.not-implemented').click(() => {alert("This feature is not implemented yet!")})

show_page("releases");
var url_parts = window.location.href.split('#')
last_part = url_parts[url_parts.length - 1]
if (last_part === 'collaborators') {
    show_page('collaborators');
} else {
    show_page("releases");
}
