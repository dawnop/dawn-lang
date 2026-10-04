cuda_tile.module @m {
  entry @leaky_relu(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9 = constant <f64: 0.0> : tile<128xf64>
    %10 = cmpf less_than ordered %7, %9 : tile<128xf64> -> tile<128xi1>
    %11 = constant <f64: 0.01> : tile<128xf64>
    %12 = mulf %7, %11 rounding<nearest_even> : tile<128xf64>
    %13 = select %10, %12, %7 : tile<128xi1>, tile<128xf64>
    %14 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %15 = make_tensor_view %14, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %16 = make_partition_view %15 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %17 = store_view_tko weak %13, %16[%4] token=%8 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
