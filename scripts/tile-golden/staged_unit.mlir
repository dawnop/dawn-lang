cuda_tile.module @m {
  entry @staged_unit(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [512], strides = [1] : tensor_view<512xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12 = constant <i32: 0> : tile<i32>
    %13 = cmpi equal %9, %12, signed : tile<i32> -> tile<i1>
    %14 = if %13 -> (tile<128xf64>) {
      %15 = addf %7, %7 rounding<nearest_even> : tile<128xf64>
      yield %15 : tile<128xf64>
    } else {
      %16 = mulf %7, %7 rounding<nearest_even> : tile<128xf64>
      yield %16 : tile<128xf64>
    }
    %17 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %18 = make_tensor_view %17, shape = [512], strides = [1] : tensor_view<512xf64, strides=[1]>
    %19 = make_partition_view %18 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>
    %20 = store_view_tko weak %14, %19[%4] token=%0 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
