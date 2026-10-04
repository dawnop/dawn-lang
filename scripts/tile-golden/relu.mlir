cuda_tile.module @m {
  entry @relu(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9 = constant <f64: 0.0> : tile<128xf64>
    %10 = maxf %7, %9 : tile<128xf64>
    %11 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %12 = make_tensor_view %11, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %13 = make_partition_view %12 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %14 = store_view_tko weak %10, %13[%4] token=%8 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
