cuda_tile.module @m {
  entry @loop_none(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [128], strides = [1] : tensor_view<128xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<128xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<128xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9, %10 = loop iter_values(%11 = %7, %12 = %8) : tile<128xf64>, token -> (tile<128xf64>, token) {
      %13 = reduce %11 dim=0 identities=[-Infinity : f64] : tile<128xf64> -> tile<f64> (%14: tile<f64>, %15: tile<f64>) {
        %16 = maxf %14, %15 : tile<f64>
        yield %16 : tile<f64>
      }
      %17 = constant <f64: 1.0> : tile<f64>
      %18 = cmpf greater_than ordered %17, %13 : tile<f64> -> tile<i1>
      %19 = constant <f64: 1000.0> : tile<128xf64>
      %20 = addf %11, %19 rounding<nearest_even> : tile<128xf64>
      if %18 {
        break %11, %12 : tile<128xf64>, token
      } else {
        yield
      }
      continue %20, %12 : tile<128xf64>, token
    }
    %21 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %22 = make_tensor_view %21, shape = [128], strides = [1] : tensor_view<128xf64, strides=[1]>
    %23 = make_partition_view %22 : partition_view<tile=(128), padding_value = zero, tensor_view<128xf64, strides=[1]>, dim_map=[0]>
    %24 = store_view_tko weak %9, %23[%4] token=%10 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<128xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
