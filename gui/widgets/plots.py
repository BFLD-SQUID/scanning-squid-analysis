import matplotlib.figure
from matplotlib import cm
from matplotlib import transforms
import matplotlib.pyplot as plt
plt.style.use('seaborn')
#plt.style.use('ggplot')
#plt.style.use('default')
matplotlib.rcParams.update({'font.size': 14})
from matplotlib.widgets import Slider
from mpl_toolkits.axes_grid1 import make_axes_locatable
import matplotlib.gridspec as gridspec
import numpy as np
from scipy.linalg import lstsq
from scipy.ndimage.interpolation import rotate
from scipy.io import savemat
import h5py
import pyqtgraph.exporters
import pyqtgraph as pg
import pickle
from ..qt import *
from .sliders import SliderWidget
from ..utils import *

mpl_cmaps = ('viridis', 'plasma', 'inferno', 'magma', 'cividis', 'Greys')
qt_cmaps = ('thermal', 'flame', 'yellowy', 'bipolar', 'grey')#, 'spectrum', 'cyclic', 'greyclip')
plot_lw = 3

__all__ = ['DataSetPlotter']

class PlotWidget(QtWidgets.QWidget):
    """Plotting widget comprised of a matplotlib canvas and a pyqtgraph widget, along with some
    options like slices of image data, axis transforms, etc.
    """
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.current_data = None
        self.exp_data = {}

        # matplotlib stuff
        self.fig = matplotlib.figure.Figure()
        self.fig.patch.set_alpha(1)
        self.fig.tight_layout()
        self.fig.subplots_adjust(bottom=0.15)
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setParent(self)
        self.canvas.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)

        # pyqtgraph stuff
        self.pyqt_plot = SlicePlotWidget(parent=self)
        self.pyqt_imview = SliceableImageView(parent=self)
        self.pyqt_plot.hide()
        self.pyqt_imview.hide()
        pyqt_top_widgets = QtWidgets.QWidget(parent=self)
        pyqt_bottom_widgets = QtWidgets.QWidget(parent=self)
        pyqt_top_layout = QtWidgets.QVBoxLayout(pyqt_top_widgets)
        pyqt_bottom_layout = QtWidgets.QVBoxLayout(pyqt_bottom_widgets)
        pyqt_top_layout.addWidget(self.pyqt_plot)
        pyqt_top_layout.addWidget(self.pyqt_imview)
        pyqt_bottom_layout.addWidget(self.pyqt_imview.x_slice_widget)
        pyqt_bottom_layout.addWidget(self.pyqt_imview.y_slice_widget)
        self.pyqt_imview.x_slice_widget.hide()
        self.pyqt_imview.y_slice_widget.hide()
        self.pyqt_splitter = QtWidgets.QSplitter(Qt.Vertical, parent=self)
        self.pyqt_splitter.hide()
        self.pyqt_splitter.addWidget(pyqt_top_widgets)
        self.pyqt_splitter.addWidget(pyqt_bottom_widgets)
        self.pyqt_splitter.setStretchFactor(1,1.5)

        # plot options
        self.option_layout = QtWidgets.QHBoxLayout()
        self._setup_cmap()
        self._setup_background_subtraction()
        self._setup_transforms()
        self._setup_slices()
        self._setup_options()
        self.slice_state = 1 # no slices
        self.set_slice()

        # main layout
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(self.option_layout)
        layout.addWidget(self.backsub_widget)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)
        layout.addWidget(self.pyqt_splitter)
        layout.addWidget(self.rotate_widget)

    def _setup_cmap(self):
        """Setup the UI for selecting matplotlib and pyqtgraph colormaps.
        """
        self.mpl_cmap = 'viridis'
        self.mpl_cmap_selector = QtWidgets.QComboBox()
        self.mpl_cmap_selector.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        self.qt_cmap_selector = QtWidgets.QComboBox()
        self.qt_cmap_selector.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)

        cmap_widget = QtWidgets.QGroupBox('Colormaps')
        mpl_cmap_widget = QtWidgets.QGroupBox('matplotlib')
        mpl_cmap_layout = QtWidgets.QHBoxLayout(mpl_cmap_widget)
        mpl_cmap_layout.addWidget(self.mpl_cmap_selector)
        qt_cmap_widget = QtWidgets.QGroupBox('pyqtgraph')
        qt_cmap_layout = QtWidgets.QHBoxLayout(qt_cmap_widget)
        qt_cmap_layout.addWidget(self.qt_cmap_selector)
        cmap_layout = QtWidgets.QHBoxLayout(cmap_widget)
        mpl_cmap_widget.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.Minimum)
        qt_cmap_widget.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.Minimum)
        cmap_layout.addWidget(mpl_cmap_widget)
        cmap_layout.addWidget(qt_cmap_widget)
        self.option_layout.addWidget(cmap_widget)

        self.mpl_cmap_selector.currentIndexChanged.connect(self.set_cmap_mpl)
        for name in mpl_cmaps:
            self.mpl_cmap_selector.addItem(name)
        self.mpl_cmap_selector.setCurrentIndex(0)
        self.qt_cmap_selector.currentIndexChanged.connect(self.set_cmap_qt)
        for name in qt_cmaps:
            self.qt_cmap_selector.addItem(name)
        self.qt_cmap_selector.setCurrentIndex(0)

    def _setup_background_subtraction(self):
        """Setup UI for global or line-by-line background subtraction.
        """
        self.backsub_radio = QtWidgets.QButtonGroup()
        backsub_buttons = [QtWidgets.QRadioButton(s) for s in ('none', 'min', 'max', 'mean', 'median', 'linear')]
        backsub_buttons[0].setChecked(True)
        self.backsub_widget = QtWidgets.QGroupBox('Background subtraction')
        self.backsub_widget.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Minimum)
        backsub_layout = QtWidgets.QHBoxLayout(self.backsub_widget)
        for i, b in enumerate(backsub_buttons):
            backsub_layout.addWidget(b)
            self.backsub_radio.addButton(b, i)
        self.backsub_radio.buttonClicked.connect(self.replot)

        self.line_backsub_radio = QtWidgets.QButtonGroup()
        self.line_backsub_btn = QtWidgets.QCheckBox('line-by-line')
        self.line_backsub_btn.setChecked(False)
        self.x_line_backsub_btn, self.y_line_backsub_btn = xy_btns = [QtWidgets.QRadioButton(s) for s in ('x', 'y')]
        xy_btns[0].setChecked(True)
        backsub_layout.addWidget(self.line_backsub_btn)
        for i, b in enumerate(xy_btns):
            b.setDisabled(True)
            backsub_layout.addWidget(b)
            self.line_backsub_radio.addButton(b, i)
        
        self.line_backsub_btn.stateChanged.connect(self.update_line_by_line)
        self.line_backsub_radio.buttonClicked.connect(self.replot)

    def _setup_transforms(self):
        """Setup UI for axis transformations. Currently this is only rotation.
        TODO: Add flipud/fliplr?
        """
        self.rotate_widget = QtWidgets.QGroupBox('Rotate')
        rotate_layout = QtWidgets.QVBoxLayout()
        self.rotate_widget.setLayout(rotate_layout)
        self.rotate_slider = SliderWidget(-180, 180, 0, 60)
        rotate_layout.addWidget(self.rotate_slider)
        self.rotate_slider.value_box.valueChanged.connect(self.replot)

    def _setup_slices(self):
        """Setup UI for slices of image/2D data.
        """
        self.slice_radio = QtWidgets.QButtonGroup()
        slice_buttons = [QtWidgets.QRadioButton(s) for s in ('none', 'x', 'y')]
        slice_buttons[0].setChecked(True)
        slice_widget = QtWidgets.QGroupBox('Slice')
        slice_layout = QtWidgets.QVBoxLayout(slice_widget)
        for i, b in enumerate(slice_buttons):
            slice_layout.addWidget(b)
            self.slice_radio.addButton(b, i)
        self.option_layout.addWidget(slice_widget)
        self.slice_radio.buttonClicked.connect(self.set_slice)
        slice_widget.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Minimum)

    def _setup_options(self):
        """Setup UI for other plot options.
        """
        opt_group = QtWidgets.QGroupBox('Plot options')
        opt_layout = QtWidgets.QVBoxLayout()
        opt_group.setLayout(opt_layout)
        plot_opts = [
            ('pyqtgraph', False),
            ('histogram', True),
            ('zoom to fit', True),
            ('grid', True),
        ]
        self.opt_checks = {}
        for name, checked in plot_opts:
            btn = QtWidgets.QCheckBox(name)
            btn.setChecked(checked)
            opt_layout.addWidget(btn)
            btn.stateChanged.connect(self.replot)
            self.opt_checks[name] = btn
        self.option_layout.addWidget(opt_group)

    def set_cmap_mpl(self, idx):
        """Set the matplotlib colormap.
        Args:
            idx (int): Index of the requested colormap in self.mpl_cmap_selector.
        """
        name = str(self.mpl_cmap_selector.itemText(idx))
        if not name:
            return
        self.mpl_cmap = name
        self.replot()

    def set_cmap_qt(self, idx):
        """Set the pyqtgraph colormap.
        Args:
            idx (int): Index of the requested colormap in self.qt_cmap_selector.
        """
        name = str(self.qt_cmap_selector.itemText(idx))
        if not name:
            return
        self.pyqt_imview.set_cmap(name)

    def get_opt(self, optname):
        """Returns True if option `optname` is checked, else False.
        Args:
            optname (str): Name of plot option to check.
        """
        return bool(self.opt_checks[optname].isChecked())

    def plot_arrays(self, xs, ys, zs=None, title=''):
        """Plots data based on dimension and all user-selected options, transforms, etc.
        Args:
            xs (tuple[str, np.ndarray[pint.Quantity]]): x data in the form of a
                tuple of (name, 0D or 1D array of pint.Quantities).
            ys (tuple[str, np.ndarray[pint.Quantity]]): y data in the form of a
                tuple of (name, 0D or 1D array of pint.Quantities).
            zs (optional, tuple[str, np.ndarray[pint.Quantity]]): None if plotting 1D data, else
                z data in the form of a tuple of (name, 2D array of pint.Quantities). Default: None.
            title (optional, str): Title for matplotlib figure. Default: ''.
        """
        self.fig_title = title
        self.fig.clear()
        self.pyqt_plot.clear()
        self.toolbar.hide()
        self.canvas.hide()
        self.pyqt_splitter.hide()
        self.pyqt_plot.hide()
        self.pyqt_imview.hide()
        if zs is None: # 1d data
            self.line_backsub_btn.setChecked(False)
            self.line_backsub_btn.setDisabled(True)
            self.pyqt_imview.x_slice_widget.hide()
            self.pyqt_imview.y_slice_widget.hide()
            self.plot_1d(xs, ys)
        else: # 2d data
            self.line_backsub_btn.setDisabled(False)
            angle = self.rotate_slider.value_box.value() # degrees
            if self.slice_state == 0:
                slice_state = None
            elif self.slice_state == 1:
                slice_state = 'x'
                self.pyqt_imview.x_slice_widget.show()
                self.pyqt_imview.y_slice_widget.hide()
            elif self.slice_state == 2:
                slice_state = 'y'
                self.pyqt_imview.x_slice_widget.hide()
                self.pyqt_imview.y_slice_widget.show()
            self.plot_2d(xs, ys, zs, angle=angle, slice_state=slice_state)
        self.fig.suptitle(self.fig_title, fontsize=12)
        self.canvas.draw()

    def plot_1d(self, xs, ys):
        """Plot 1D data according to user-selected options, transformations, etc.
        Args:
            xs (tuple[str, np.ndarray[pint.Quantity]]): x data in the form of a
                tuple of (name, 0D or 1D array of pint.Quantities).
            ys (tuple[str, np.ndarray[pint.Quantity]]): y data in the form of a
                tuple of (name, 0D or 1D array of pint.Quantities).
        """
        label = ys[0]
        xlabel = f'{xs[0]} [{xs[1].units}]'
        ylabel = f'{ys[0]} [{ys[1].units}]'
        marker = '.'
        ymin, ymax = np.min(ys[1]), np.max(ys[1])
        if self.get_opt('pyqtgraph'):
            self.plot_1d_qt(xs, ys, xlabel, ylabel, label)
            self.pyqt_plot.show()
            self.pyqt_splitter.show()
        else:
            self.plot_1d_mpl(xs, ys, xlabel, ylabel, marker, ymin, ymax, label)
            self.toolbar.show()
            self.canvas.show()
        self.rotate_widget.hide()
        self.exp_data = {d[0]: {'array': d[1].magnitude, 'unit': str(d[1].units)} for d in (xs, ys)}

    def plot_1d_qt(self, xs, ys, xlabel, ylabel, label):
        """Plot 1D data on self.pyqt_plot.
        Args:
            xs (tuple[str, np.ndarray[pint.Quantity]]): x data in the form of a
                tuple of (name, 0D or 1D array of pint.Quantities).
            ys (tuple[str, np.ndarray[pint.Quantity]]): y data in the form of a
                tuple of (name, 0D or 1D array of pint.Quantities).
            xlabel (str): x-axis label.
            ylabel (str): y-axis label.
            label (str): Label for legend.
        """
        self.pyqt_plot.setLabels(bottom=(xlabel,), left=(ylabel,))
        self.pyqt_plot.plot(xs[1].magnitude, ys[1].magnitude, symbol='o', pen=None)

    def plot_1d_mpl(self, xs, ys, xlabel, ylabel, marker, ymin, ymax, label):
        """Plot 1D data on self.fig.
        Args:
            xs (tuple[str, np.ndarray[pint.Quantity]]): x data in the form of a
                tuple of (name, 0D or 1D array of pint.Quantities).
            ys (tuple[str, np.ndarray[pint.Quantity]]): y data in the form of a
                tuple of (name, 0D or 1D array of pint.Quantities).
            xlabel (str): x-axis label.
            ylabel (str): y-axis label.
            marker (str): Plot point marker.
            ymin (float): Minimum y value.
            ymax (float): Maximum y value.
            label (str): Label for legend.
        """
        ax = self.fig.add_subplot(111)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.plot(xs[1].magnitude, ys[1].magnitude, marker, label=label)
        if not self.get_opt('zoom to fit'):
            ax.set_ylim(ymin, ymax)
        ax.grid(self.get_opt('grid'))
        self.fig.tight_layout()
        self.fig.subplots_adjust(top=0.9, bottom=0.15)
        ax.legend()

    def plot_2d(self, xs, ys, zs, cmap=None, angle=0, slice_state=None):
        """Plot 2D data according to user-selected options, transformations, etc.
        Args:
            xs (tuple[str, np.ndarray[pint.Quantity]]): x data in the form of a
                tuple of (name, 0D or 1D array of pint.Quantities).
            ys (tuple[str, np.ndarray[pint.Quantity]]): y data in the form of a
                tuple of (name, 0D or 1D array of pint.Quantities).
            zs (tuple[str, np.ndarray[pint.Quantity]]): z data in the form of a tuple of
                (name, 2D array of pint.Quantities).
            cmap (optional, str): Name of matplotlib colormap. Default: None.
            angle (optional, float): Angle by which to rotate image (degrees). Default: 0.
            slice_state (optional, str): Requested 1D slice state, in (None, 'x', 'y'). Default: None.
        """
        cmap = cmap or self.mpl_cmap
        xlabel = f'{xs[0]} [{xs[1].units}]'
        ylabel = f'{ys[0]} [{ys[1].units}]'
        zlabel = f'{zs[0]} [{zs[1].units}]'       
        zmin, zmax = np.nanmin(zs[1]), np.nanmax(zs[1])
        self.rotate_widget.show()
        if self.get_opt('pyqtgraph'):
            self.plot_2d_qt(xs, ys, zs, xlabel, ylabel, zlabel, angle=angle)
            self.pyqt_imview.show()
            self.pyqt_splitter.show()
        else:
            # maintain a reference to the matplotlib slider so that it doesn't die
            self.slider = self.plot_2d_mpl(xs, ys, zs, xlabel, ylabel, zlabel, 
                                vmin=zmin, vmax=zmax, cmap=cmap, angle=angle, slice_state=slice_state)
            self.toolbar.show()
            self.canvas.show()

    def plot_2d_qt(self, xs, ys, zs, xlabel, ylabel, zlabel, angle=0):
        """Plot 2D data on self.pyqt_imview.
        Args:
            xs (tuple[str, np.ndarray[pint.Quantity]]): x data in the form of a
                tuple of (name, 0D or 1D array of pint.Quantities).
            ys (tuple[str, np.ndarray[pint.Quantity]]): y data in the form of a
                tuple of (name, 0D or 1D array of pint.Quantities).
            zs (tuple[str, np.ndarray[pint.Quantity]]): z data in the form of a tuple of
                (name, 2D array of pint.Quantities).
            xlabel (str): x-axis label.
            ylabel (str): y-axis label.
            zlabel (str): z-axis label.
            angle (optional, float): Angle by which to rotate image (degrees). Default: 0.
        """
        pos = np.nanmin(xs[1][0].magnitude), np.nanmin(ys[1][0].magnitude)
        scale = np.ptp(xs[1].magnitude) / zs[1].shape[0], np.ptp(ys[1].magnitude) / zs[1].shape[1]
        z = rotate(zs[1].magnitude.T, angle, cval=np.nanmin(zs[1].magnitude))
        self.pyqt_imview.setImage(z, pos=pos, scale=scale)
        self.pyqt_imview.setLabels(xlabel=xlabel, ylabel=ylabel, zlabel=zlabel)
        self.pyqt_imview.autoRange()
        self.pyqt_imview.set_histogram(self.get_opt('histogram'))
        self.exp_data = {d[0]: {'array': d[1].magnitude, 'unit': str(d[1].units)} for d in (xs, ys)}
        self.exp_data[zs[0]] = {'array': z, 'unit': str(zs[1].units)}

    def plot_2d_mpl(self, xs, ys, zs, xlabel, ylabel, zlabel, cmap=None, angle=0, slice_state=None, **kwargs):
        """Plot 2D data on self.fig.
        Args:
            xs (tuple[str, np.ndarray[pint.Quantity]]): x data in the form of a
                tuple of (name, 0D or 1D array of pint.Quantities).
            ys (tuple[str, np.ndarray[pint.Quantity]]): y data in the form of a
                tuple of (name, 0D or 1D array of pint.Quantities).
            zs (tuple[str, np.ndarray[pint.Quantity]]): z data in the form of a tuple of
                (name, 2D array of pint.Quantities).
            xlabel (str): x-axis label.
            ylabel (str): y-axis label.
            zlabel (str): z-axis label.
            cmap (optional, str): Name of matplotlib colormap. Default: None.
            angle (optional, float): Angle by which to rotate image (degrees). Default: 0.
            slice_state (optional, str): Requested 1D slice state, in (None, 'x', 'y'). Default: None.
            kwargs (optional, dict): Keyword arguments passed to plt.pcolormesh constructor.
        """
        if slice_state is None:
            plt.rcParams.update({'font.size': 14})
            self.fig.subplots_adjust(top=0.9, bottom=0.15, left=0.0, right=0.85, hspace=0.0, wspace=0)
            ax = self.fig.add_subplot(111)
            ax.set_xlabel(xlabel)
            ax.set_ylabel(ylabel)
            x0, y0 = np.mean(xs[1].magnitude), np.mean(ys[1].magnitude)
            tr = transforms.Affine2D().rotate_deg_around(x0, y0, angle)
            im = ax.pcolormesh(xs[1], ys[1], zs[1].magnitude, cmap=cmap,
                                transform=(tr + ax.transData), **kwargs)
            cbar = self.fig.colorbar(im)
            cbar.set_label(zlabel)
            ax.set_aspect('equal')
            z = rotate(zs[1].magnitude.T, angle, cval=np.nan)
            x = np.linspace(*ax.get_xlim(), z.shape[1])
            y = np.linspace(*ax.get_ylim(), z.shape[0])
            self.exp_data = {
                xs[0]: {'array': x, 'unit': str(xs[1].units)},
                ys[0]: {'array': y, 'unit': str(ys[1].units)},
                zs[0]: {'array': z, 'unit': str(zs[1].units)}
            }
        else:
            plt.rcParams.update({'font.size': 10})
            self.fig.subplots_adjust(top=0.9, bottom=0.05, left=0.0, right=1.0, hspace=0.5, wspace=0.0)
            ax0 = plt.subplot2grid((12,12), (0,2), colspan=6, rowspan=5, fig=self.fig)
            ax0.set_xlabel(xlabel)
            ax0.set_ylabel(ylabel)
            x0, y0 = np.mean(xs[1].magnitude), np.mean(ys[1].magnitude)
            tr = transforms.Affine2D().rotate_deg_around(x0, y0, angle)
            im = ax0.pcolormesh(xs[1], ys[1], zs[1].magnitude, cmap=cmap,
                                transform=(tr + ax0.transData), **kwargs)
            cbar = self.fig.colorbar(im)
            cbar.set_label(zlabel)
            ax0.set_aspect('equal')
            ax1 = plt.subplot2grid((12,12), (7,2), colspan=8, rowspan=5, fig=self.fig)
            ax1.grid(self.get_opt('grid'))
            xlab = xlabel if slice_state == 'x' else ylabel
            label = zlabel.split(' ')[:1] + [''.join(zlabel.split(' ')[1:])]
            ylab = '\n'.join(label)
            if slice_state == 'x':
                line, = ax1.plot(xs[1].magnitude, zs[1].magnitude[:,0], lw=plot_lw)
                cut = ax0.axhline(y=ax0.get_ylim()[0], color='k', alpha=0.8, lw=2)
            else:
                line, = ax1.plot(ys[1].magnitude, zs[1].magnitude[0,:], lw=plot_lw)
                cut = ax0.axvline(x=ax0.get_xlim()[0], color='k', alpha=0.8, lw=2)
            ax1.set_xlabel(xlab)
            ax1.set_ylabel(ylab)
            divider = make_axes_locatable(ax1)
            ax_slider = divider.append_axes('bottom', size='15%', pad=0.45)
            idx_label = 'y' if slice_state == 'x' else 'x'
            idx = 1 if slice_state == 'x' else 0
            slider = Slider(ax_slider, f'{idx_label} index', 0, zs[1].shape[idx] - 1,
                            valinit=0, valstep=1, valfmt='%i')
            z = rotate(zs[1].magnitude.T, angle, cval=np.nan)
            x = np.linspace(*ax0.get_xlim(), z.shape[1])
            y = np.linspace(*ax0.get_ylim(), z.shape[0])   
            # update plot on slider changed event
            def update(val):
                i = int(slider.val)
                z = rotate(zs[1].magnitude.T, angle, cval=np.nan)
                x = np.linspace(*ax0.get_xlim(), z.shape[1])
                y = np.linspace(*ax0.get_ylim(), z.shape[0])
                margin = 0.025
                if slice_state == 'x':
                    slider.valmax = len(y) - 1
                    line.set_data(x, z[:,i])
                    rng = np.nanmax(x) - np.nanmin(x)
                    xmin = np.nanmin(x) - margin * rng
                    xmax = np.nanmax(x) + margin * rng
                    cut.set_ydata(2*[y[i]])
                else:
                    slider.valmax = len(x) - 1
                    line.set_data(y, z[i,:])
                    rng = np.nanmax(y) - np.nanmin(y)
                    xmin = np.nanmin(y) - margin * rng
                    xmax = np.nanmax(y) + margin * rng
                    cut.set_xdata(2*[x[i]])
                ax1.set_xlim(xmin, xmax)
                slider.ax.set_xlim(slider.valmin,slider.valmax)
                ydata = line.get_ydata()
                vmin, vmax = np.nanmin(ydata), np.nanmax(ydata)
                margin = 0.1
                rng = vmax - vmin
                vmin = vmin - margin * rng
                vmax = vmax + margin * rng
                try:
                    ax1.set_ylim(vmin, vmax)
                except ValueError: # vmin == vmax
                    pass
                if slice_state == 'x':
                    self.exp_data['slice'] = {
                        xs[0]: {'array': line.get_xdata(), 'unit': str(xs[1].units)},
                        zs[0]: {'array': line.get_ydata(), 'unit': str(zs[1].units)},
                        'index': int(slider.val)
                    }
                elif slice_state == 'y':
                    self.exp_data['slice'] = {
                        ys[0]: {'array': line.get_xdata(), 'unit': str(ys[1].units)},
                        zs[0]: {'array': line.get_ydata(), 'unit': str(zs[1].units)},
                        'index': int(slider.val)
                    }
                self.fig.tight_layout()
                self.canvas.draw()
            update(0)
            slider.on_changed(update)
            self.exp_data = {
                xs[0]: {'array': x, 'unit': str(xs[1].units)},
                ys[0]: {'array': y, 'unit': str(ys[1].units)},
                zs[0]: {'array': z, 'unit': str(zs[1].units)}
            }            
            return slider # return slider handle to maintain connection to it

    def replot(self):
        """Update the current plot from self.current_data.
        """
        if self.current_data is not None:
            xs, ys, zs = self.current_data[:]
            name = ys[0] if zs is None else zs[0]
            self.fig_title = f"{self.dataset.metadata['location']} [{name}]"
            self.subtract_background()

    def set_slice(self, idx=None, replot=True):
        """Capture the user-requested slice state.
        """
        if isinstance(idx, QtWidgets.QRadioButton):
            idx = self.slice_radio.id(idx)
        if idx is None:
            idx = self.slice_radio.checkedId()
        self.slice_state = idx
        self.update_slice()
        if replot:
            self.replot()

    def update_slice(self):
        """Show or hide pyqtgraph slice widgets based on self.slice_state.
        """
        if self.slice_state == 0:
            self.pyqt_imview.x_slice_widget.hide()
            self.pyqt_imview.y_slice_widget.hide()
        elif self.slice_state == 1:
            self.pyqt_imview.x_slice_widget.show()
            self.pyqt_imview.y_slice_widget.hide()
        elif self.slice_state == 2:
            self.pyqt_imview.x_slice_widget.hide()
            self.pyqt_imview.y_slice_widget.show()
        else:
            raise ValueError("Unknown Slice State: {}".format(self.slice_state))

    def update_line_by_line(self):
        """Enable/disable line-by-line background subtraction based on self.line_backsub_btn.
        """
        if self.line_backsub_btn.isChecked():
            self.x_line_backsub_btn.setDisabled(False)
            self.y_line_backsub_btn.setDisabled(False)
        else:
            self.x_line_backsub_btn.setDisabled(True)
            self.y_line_backsub_btn.setDisabled(True)
        self.replot()

    def subtract_background(self, idx=None):
        """Perform global or line-by-line background subtraction.
        """
        if self.current_data is None:
            return
        if isinstance(idx, QtWidgets.QRadioButton):
            idx = self.backsub_radio.id(idx)
        idx = idx or self.backsub_radio.checkedId()
        xs, ys, zs = self.current_data[:] # copy self.current_data to avoid changing it
        line_by_line = self.line_backsub_btn.isChecked()
        if line_by_line and zs is not None:
            funcs = (lambda x: 0, np.min, np.max, np.mean, np.median,
                        lambda y, x=xs[1].magnitude: self._subtract_line(x, y))
            axis = self.line_backsub_radio.checkedId()
            z = self._subtract_line_by_line(np.copy(zs[1].magnitude), axis, funcs[idx])
            zs = [zs[0], z * zs[1].units] # restore units after background subtraction
        if idx == 1: # min
            if zs is None:
                ys = [ys[0], ys[1] - np.min(ys[1])]
            elif not line_by_line:
                zs = [zs[0], zs[1] - np.min(zs[1])]
        elif idx == 2: # max
            if zs is None:
                ys = [ys[0], ys[1] - np.max(ys[1])]
            elif not line_by_line:
                zs = [zs[0], zs[1] - np.max(zs[1])] 
        elif idx == 3: # mean
            if zs is None:
                ys = [ys[0], ys[1] - np.mean(ys[1])]
            elif not line_by_line:
                zs = [zs[0], zs[1] - np.mean(zs[1])]
        elif idx == 4: # median
            if zs is None:
                ys = [ys[0], ys[1] - ys[1].units * np.median(ys[1])]
            elif not line_by_line:
                zs = [zs[0], zs[1] - zs[1].units * np.median(np.reshape(zs[1], (-1,1)))]
        elif idx == 5: # linear
            if zs is None:
                slope, offset = np.polyfit(xs[1].magnitude, ys[1].magnitude, 1)
                ys = [ys[0], ys[1] -  ys[1].units * (slope * xs[1].magnitude + offset)]
            elif not line_by_line:
                X, Y = np.meshgrid(xs[1], ys[1], indexing='ij')
                x = np.reshape(X, (-1, 1))
                y = np.reshape(Y, (-1, 1))
                data = np.reshape(zs[1].magnitude, (-1, 1))
                z = np.column_stack((x, y, np.ones_like(x)))
                plane, _, _, _ = lstsq(z, data)
                zs = [zs[0], zs[1] - zs[1].units * (plane[0] * X + plane[1] * Y + plane[2])]
        self.plot_arrays(xs, ys, zs=zs, title=self.fig_title)

    def export_mpl(self, dpi=300):
        """Open dialog to export matplotlib figure.
        Args:
            dpi (int): DPI with which to save the figure.
        """
        if self.dataset is None:
            return
        name = self.fig_title.split('/')[-1].replace(' ', '')
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Export matplotlib', name,
                                                    'PNG (*.png)')
        self.fig.savefig(path, dpi=dpi)

    def export_qt(self, width=1200):
        """Open dialog to export pyqtgraph figure.
        Args:
            width (int): Figure width in pixels (I think).
        Note: this is not currently used by the GUI because the pyqtgraph figures are ugly.
        """
        if self.dataset is None:
            return
        name = self.fig_title.split('/')[-1].replace(' ', '')
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Export pyqtgraph', name,
                                                    'PNG Image (*.png);; JPG Image (*.jpg)')
        plot = self.pyqt_plot.plotItem if self.pyqt_plot.isVisible() else self.pyqt_imview.scene
        exporter = pg.exporters.ImageExporter(plot)
        exporter.parameters()['width'] = width
        exporter.export(path)

    def export_data(self):
        """Open dialog to export current data (post transformations and background subtraction)
        to .mat, .h5, or .pickle files.
        """
        if not self.exp_data:
            return
        name = self.fig_title.split('/')[-1].replace(' ', '')
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Export current data', name,
                                                    'MAT (*.mat);;HDF5 (*.h5);;pickle (*.pickle)')
        if path.endswith('mat'):
            try:
                savemat(path, self.exp_data)
            except:
                pass
        elif path.endswith('h5'):
            try:
                with h5py.File(path) as df:
                    set_h5_attrs(df, self.exp_data)
            except:
                pass
        elif path.endswith('pickle'):
            try:
                with open(path, 'wb') as f:
                    pickle.dump(self.exp_data, f)
            except:
                pass

    def _subtract_line_by_line(self, zdata, axis, func):
        """Perform line-by-line background subtraction of `zdata` along axis `axis` according
        to callable `func`.
        Args:
            zdata (np.ndarray): 2D data for which you want to do background subtraction.
            axis (int): Axis along which you want to do line-by-line background subtraction.
            func (callable): Function applied to each line to calculate the value to subtract
                (e.g. np.min, np.mean, etc.)
        Returns:
            np.ndarray: zdata with background subtracted line-by-line.
        """
        if axis: # y
            for i in range(zdata.shape[axis]):
                zdata[:,i] -= func(zdata[:,i])
        else: #x
            for i in range(zdata.shape[axis]):
                zdata[i,:] -= func(zdata[i,:])
        return zdata

    def _subtract_line(self, x, y):
        """Subtract the best-fit line `slope * x + offset` from array `y`.
        Args:
            x (np.ndarray): OD or 1D array of x values.
            y (np.ndarray): 0D or 1D array of y values.
        Returns:
            np.ndarray: y with best-fit line subtracted.
        """
        slope, offset = np.polyfit(x, y, 1)
        return y - (slope * x + offset)

class DataSetPlotter(PlotWidget):
    """PlotWidget with functionality specific to scanning-squid datasets.
    """
    def __init__(self, dataset=None, parent=None):
        super().__init__(parent=parent)
        self.dataset = dataset
        self.arrays = None
        self.indep_vars = None
        arrays_widget = QtWidgets.QGroupBox('Arrays')
        arrays_layout = QtWidgets.QHBoxLayout(arrays_widget)
        arrays_widget.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.Minimum)
        self.selector = QtWidgets.QComboBox()
        arrays_layout.addWidget(self.selector)
        self.option_layout.insertWidget(0, arrays_widget)
        self.selector.currentIndexChanged.connect(self.set_plot)

        self.xy_units_box = QtWidgets.QCheckBox('real x-y units')
        self.xy_units_box.setChecked(False)
        self.xy_units = QtWidgets.QLineEdit()
        self.xy_units.setText('Enter length unit')
        self.xy_units.setDisabled(True)
        xy_units_widget = QtWidgets.QWidget()
        xy_units_layout = QtWidgets.QVBoxLayout()
        xy_units_widget.setLayout(xy_units_layout)
        xy_units_layout.addWidget(self.xy_units_box)
        xy_units_layout.addWidget(self.xy_units)
        arrays_layout.addWidget(xy_units_widget)
        self.xy_units_box.stateChanged.connect(self.update_xy_units)
        self.xy_units.returnPressed.connect(self.update)

    def get_arrays(self):
        """Create a dict of arrays from self.dataset.
        """
        if self.dataset is None:
            return
        if '_scan_' in self.dataset.location:
            if self.xy_units_box.isChecked():
                try:
                    self.arrays = scan_to_arrays(self.dataset, xy_unit=self.xy_units.text())
                except:
                    self.arrays = scan_to_arrays(self.dataset, xy_unit='um')
                    self.xy_units.setText('um')
            else:
                self.arrays = scan_to_arrays(self.dataset)
            self.indep_vars = ('x', 'y')
        elif '_td_cap_' in self.dataset.location:
            self.arrays = td_to_arrays(self.dataset)
            self.indep_vars = ('height',)
        self.selector.clear()
        items = []
        for name in self.arrays.keys():
            if name.lower() not in self.indep_vars:
                items.append(name)
                self.selector.addItem(name)
        self.selector.setCurrentIndex(0)
        self.set_plot(0)

    def set_plot(self, idx):
        """Set current plot to the given index of self.selector.
        Args:
            idx (int): Index of requested plot.
        """
        name = str(self.selector.itemText(idx))
        if not name:
            return
        self.set_plot_from_name(name)

    def set_plot_from_name(self, name):
        """Set current plot by name.
        Args:
            name (str): Name of requested plot/array.
        """
        if len(self.indep_vars) == 1:
            xs = [self.indep_vars[0], self.arrays[self.indep_vars[0]]]
            ys = [name, self.arrays[name]]
            zs = None
        elif len(self.indep_vars) == 2:
            xs, ys = ([var, self.arrays[var]] for var in self.indep_vars)
            z = self.arrays[name]
            # set nan values to the non-nan min to avoid issues with plotting
            z[np.isnan(z)] = np.nanmin(z) * z.units
            zs = [name, z]
        title = ''
        if self.dataset is not None:
            title = f"{self.dataset.metadata['location']} [{name}]"
        self.current_data = [xs, ys, zs]
        self.plot_arrays(xs, ys, zs, title)
        self.subtract_background()

    def update_xy_units(self):
        """Enable or disable user entry for x-y length units.
        """
        if self.xy_units_box.isChecked():
            self.xy_units.setText('um')
            self.xy_units.setDisabled(False)
        else:
            self.xy_units.setText('Enter length unit')
            self.xy_units.setDisabled(True)
        idx = self.selector.currentIndex()
        self.update(idx=idx)
        self.selector.setCurrentIndex(idx)

    def update(self, dataset=None, idx=0):
        """Update arrays and plot from dataset.
        """
        self.dataset = dataset or self.dataset
        self.get_arrays()
        self.backsub_radio.button(0).setChecked(True)
        self.set_plot(idx)

class ImageView(pg.ImageView):
    """pyqtgraph ImageView wrapper.
    """
    def __init__(self, **kwargs):
        kwargs['view'] = pg.PlotItem(labels=kwargs.pop('labels', None))
        super().__init__(**kwargs)
        self.view.setAspectLocked(lock=True)
        self.view.invertY(False)
        self.set_histogram(True)
        histogram_action = QtWidgets.QAction('Histogram', self)
        histogram_action.setCheckable(True)
        histogram_action.triggered.connect(self.set_histogram)
        self.scene.contextMenu.append(histogram_action)
        self.ui.histogram.gradient.loadPreset('grey')

    def set_histogram(self, visible):
        """Show or hide the histogram.
        Args:
            visible (bool): Whether you want the histogram to be visible.
        """
        self.ui.histogram.setVisible(visible)
        self.ui.roiBtn.setVisible(False)
        self.ui.normGroup.setVisible(False)
        self.ui.menuBtn.setVisible(False)

    def set_data(self, data):
        """Set the image data.
        Args:
            data (np.ndarray): 2D array of iamge data.
        """
        self.setImage(data)

    def set_cmap(self, name):
        """Set the colormap to one of pyqtgraph's presets.
        Args:
            name (str): Name of preset colormap.
        """
        self.ui.histogram.gradient.loadPreset(name)


class SlicePlotWidget(pg.PlotWidget):
    """pyqtgraph PlotWidget with crosshairs that follow mouse.
    """
    crosshair_moved = QtCore.Signal(float, float)
    def __init__(self, parametric=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cross_section_enabled = False
        self.parametric = parametric
        self.search_mode = True
        self.label = None
        self.selected_point = None
        self.plotItem.showGrid(x=True, y=True, alpha=0.5)
        self.scene().sigMouseClicked.connect(self.toggle_search)
        self.scene().sigMouseMoved.connect(self.handle_mouse_move)

    def set_data(self, data, **kwargs):
        if data is not None and len(data) > 0 and np.isfinite(data).all():
            self.clear()
            self.plot(data, **kwargs)

    def toggle_search(self, mouse_event):
        """Toggle the crosshairs tracking mouse movement on click event.
        """
        if mouse_event.double():
            if self.cross_section_enabled:
                self.hide_crosshair()
            else:
                self.add_crosshair()
        elif self.cross_section_enabled:
            self.search_mode = not self.search_mode
            if self.search_mode:
                self.handle_mouse_move(mouse_event.scenePos())

    def handle_mouse_move(self, mouse_event):
        """Depending on search_mode and cross_section_enabled, track mouse movement
        and emit a signal with the crosshair position.
        """
        if self.cross_section_enabled and self.search_mode:
            item = self.getPlotItem()
            view_coords = item.getViewBox().mapSceneToView(mouse_event)
            view_x, view_y = view_coords.x(), view_coords.y()
            # try to get data indices corresponding to mouse position
            guesses = []
            for data_item in item.items:
                if isinstance(data_item, pg.PlotDataItem):
                    xdata, ydata = data_item.xData, data_item.yData
                    index_distance = lambda i: (xdata[i]-view_x)**2 + (ydata[i] - view_y)**2
                    if self.parametric:
                        index = min(range(len(xdata)), key=index_distance)
                    else:
                        index = min(np.searchsorted(xdata, view_x), len(xdata)-1)
                        if index and xdata[index] - view_x > view_x - xdata[index - 1]:
                            index -= 1
                    pt_x, pt_y = xdata[index], ydata[index]
                    guesses.append(((pt_x, pt_y), index_distance(index), index))
            if not guesses:
                return

            (pt_x, pt_y), _, index = min(guesses, key=lambda x: x[1])
            self.selected_point = (pt_x, pt_y)
            self.v_line.setPos(pt_x)
            self.h_line.setPos(pt_y)
            self.label.setText("x={:.5f}, y={:.5f}".format(pt_x, pt_y))
            self.crosshair_moved.emit(pt_x, pt_y)

    def add_crosshair(self):
        self.h_line = pg.InfiniteLine(angle=0, movable=False)
        self.v_line = pg.InfiniteLine(angle=90, movable=False)
        self.addItem(self.h_line, ignoreBounds=False)
        self.addItem(self.v_line, ignoreBounds=False)
        if self.label is None:
            self.label = pg.LabelItem(justify="right")
            self.getPlotItem().layout.addItem(self.label, 4, 1)
        self.x_cross_index = 0
        self.y_cross_index = 0
        self.cross_section_enabled = True

    def hide_crosshair(self):
        self.removeItem(self.h_line)
        self.removeItem(self.v_line)
        self.cross_section_enabled = False

class SliceableImageView(ImageView):
    """ImageView combined with a SlicePlotWidget for both x and y slices.
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.search_mode = False
        self._connect_signals()
        self.angle = 0
        self.y_cross_index = 0
        self.x_cross_index = 0
        self.x_slice_widget = SlicePlotWidget()
        self.x_slice_widget.add_crosshair()
        self.x_slice_widget.search_mode = False
        self.pen = pg.mkPen(width=plot_lw)
        self.x_slice_widget_data = self.x_slice_widget.plot([0,0], pen=self.pen)
        self.h_line = pg.InfiniteLine(pos=0, angle=0, movable=False, pen=self.pen)
        self.view.addItem(self.h_line, ignoreBounds=False)

        self.y_slice_widget = SlicePlotWidget()
        self.y_slice_widget.add_crosshair()
        self.y_slice_widget.search_mode = False
        self.y_slice_widget_data = self.y_slice_widget.plot([0,0], pen=self.pen)
        self.v_line = pg.InfiniteLine(pos=0, angle=90, movable=False, pen=self.pen)
        self.view.addItem(self.v_line, ignoreBounds=False)

        self.x_slice_widget.crosshair_moved.connect(lambda x, _: self.set_position(x=x))
        self.y_slice_widget.crosshair_moved.connect(lambda y, _: self.set_position(y=y))

        self.text_item = pg.LabelItem(justify='right')
        self.view.layout.addItem(self.text_item, 4, 1)

    def setImage(self, *args, **kwargs):
        """Set the image and adjust ViewBox, etc.
        *args and **kwargs passed to ImageItem constructor.
        """
        if 'pos' in kwargs:
            self._x0, self._y0 = kwargs['pos']
        else:
            self._x0, self._y0 = 0, 0
        if 'scale' in kwargs:
            self._xscale, self._yscale = kwargs['scale']
        else:
            self._xscale, self._yscale = 1, 1
        # adjust to make pixel centers align on ticks
        self._x0 -= self._xscale / 2.0
        self._y0 -= self._yscale / 2.0
        if 'pos' in kwargs:
            kwargs['pos'] = self._x0, self._y0

        if self.imageItem.image is not None:
            (min_x, max_x), (min_y, max_y) = self.imageItem.getViewBox().viewRange()
            mid_x, mid_y = (max_x + min_x)/2., (max_y + min_y)/2.
        else:
            mid_x, mid_y = 0, 0

        self.h_line.setPos(mid_y)
        self.v_line.setPos(mid_x)
        super().setImage(*args, **kwargs)
        self.set_position()

    def setLabels(self, xlabel='x', ylabel='y', zlabel='z'):
        """Set x, y, and z labels.
        """
        self.view.setLabels(bottom=(xlabel,), left=(ylabel,))
        self.x_slice_widget.plotItem.setLabels(bottom=xlabel, left=zlabel)
        self.y_slice_widget.plotItem.setLabels(bottom=ylabel, left=zlabel)
        self.ui.histogram.item.axis.setLabel(text=zlabel)

    def _connect_signals(self):
        """Setup signals.
        """
        if self.imageItem.scene() is None:
            raise RuntimeError('Signal can only be connected after it has been embedded in a scene.')
        self.imageItem.scene().sigMouseClicked.connect(self.toggle_search)
        self.imageItem.scene().sigMouseMoved.connect(self.handle_mouse_move)
        self.timeLine.sigPositionChanged.connect(self.update_slice)

    def toggle_search(self, mouse_event):
        """Toggle the crosshairs tracking mouse movement on click event.
        """
        if mouse_event.double():
            return
        self.search_mode = not self.search_mode
        if self.search_mode:
            self.handle_mouse_move(mouse_event.scenePos())

    def handle_mouse_move(self, mouse_event):
        """Depending on search_mode, track mouse movement and update position text_item.
        """
        if self.search_mode:
            view_coords = self.imageItem.getViewBox().mapSceneToView(mouse_event)
            view_x, view_y = view_coords.x(), view_coords.y()
            self.set_position(view_x, view_y)

    def set_position(self, x=None, y=None):
        """Update text_item displaying x, y, and z mouse position.
        """
        if x is None:
            x = self.v_line.getXPos()
        if y is None:
            y = self.h_line.getYPos()

        item_coords = self.imageItem.getViewBox().mapFromViewToItem(self.imageItem, QtCore.QPointF(x, y))
        item_x, item_y = item_coords.x(), item_coords.y()
        max_x, max_y = self.imageItem.image.shape

        item_x = self.x_cross_index = max(min(int(item_x), max_x-1), 0)
        item_y = self.y_cross_index = max(min(int(item_y), max_y-1), 0)

        view_coords = self.imageItem.getViewBox().mapFromItemToView(self.imageItem, QtCore.QPointF(item_x+.5, item_y+.5))
        x, y = view_coords.x(), view_coords.y()

        self.v_line.setPos(x)
        self.h_line.setPos(y)
        z_val = self.imageItem.image[self.x_cross_index, self.y_cross_index]
        self.update_slice()
        self.text_item.setText('x={:.5f}, y={:.5f}, z={:.5f}'.format(x, y, z_val))

    def update_slice(self):
        """Update the current x and y slices.
        """
        zdata = self.imageItem.image
        nx, ny = zdata.shape
        x0, y0, xscale, yscale = self._x0, self._y0, self._xscale, self._yscale
        xdata = np.linspace(x0, x0+(xscale*(nx-1)), nx)
        ydata = np.linspace(y0, y0+(yscale*(ny-1)), ny)
        zval = zdata[self.x_cross_index, self.y_cross_index]
        self.x_slice_widget_data.setData(xdata, zdata[:, self.y_cross_index])
        self.x_slice_widget.v_line.setPos(xdata[self.x_cross_index])
        self.x_slice_widget.h_line.setPos(zval)
        self.y_slice_widget_data.setData(ydata, zdata[self.x_cross_index, :])
        self.y_slice_widget.v_line.setPos(ydata[self.y_cross_index])
        self.y_slice_widget.h_line.setPos(zval)
