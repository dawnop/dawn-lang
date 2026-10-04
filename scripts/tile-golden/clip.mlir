cuda_tile.module @m {
  entry @clip(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [333], strides = [1] : tensor_view<333xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(64), padding_value = zero, tensor_view<333xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(64), padding_value = zero, tensor_view<333xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<64xf64>, token
    %9 = constant <f64: -1.0> : tile<64xf64>
    %10 = maxf %7, %9 : tile<64xf64>
    %11 = constant <f64: 1.0> : tile<64xf64>
    %12 = minf %10, %11 : tile<64xf64>
    %13 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %14 = make_tensor_view %13, shape = [333], strides = [1] : tensor_view<333xf64, strides=[1]>
    %15 = make_partition_view %14 : partition_view<tile=(64), padding_value = zero, tensor_view<333xf64, strides=[1]>, dim_map=[0]>
    %16 = store_view_tko weak %12, %15[%4] token=%8 : tile<64xf64>, partition_view<tile=(64), padding_value = zero, tensor_view<333xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
