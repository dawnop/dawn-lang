cuda_tile.module @m {
  entry @view_transpose(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %3 = offset %2, %1 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %4 = make_tensor_view %3, shape = [100, 60], strides = [60, 1] : tensor_view<100x60xf64, strides=[60, 1]>
    %5 = make_partition_view %4 : partition_view<tile=(32x32), padding_value = zero, tensor_view<100x60xf64, strides=[60, 1]>, dim_map=[0, 1]>
    %6 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %7 = offset %6, %1 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %8 = make_tensor_view %7, shape = [100, 60], strides = [1, 100] : tensor_view<100x60xf64, strides=[1, 100]>
    %9 = make_partition_view %8 : partition_view<tile=(32x32), tensor_view<100x60xf64, strides=[1, 100]>, dim_map=[0, 1]>
    %10, %11, %12 = get_tile_block_id : tile<i32>
    %13, %14, %15 = get_tile_block_id : tile<i32>
    %16, %17 = load_view_tko weak %5[%10, %14] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<100x60xf64, strides=[60, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
    %18 = store_view_tko weak %16, %9[%10, %14] token=%0 : tile<32x32xf64>, partition_view<tile=(32x32), tensor_view<100x60xf64, strides=[1, 100]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
