cuda_tile.module @m {
  entry @layer_norm(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2, %3, %4 = get_num_tile_blocks : tile<i32>
    %5 = constant <i32: 256> : tile<i32>
    %6 = muli %2, %5 : tile<i32>
    %7 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %8 = make_tensor_view %7, shape = [%6], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %9 = make_partition_view %8 : partition_view<tile=(256), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %10, %11, %12 = get_tile_block_id : tile<i32>
    %13, %14 = load_view_tko weak %9[%10] token=%0 : partition_view<tile=(256), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<256xf64>, token
    %15 = reduce %13 dim=0 identities=[0.0 : f64] : tile<256xf64> -> tile<f64> (%16: tile<f64>, %17: tile<f64>) {
      %18 = addf %16, %17 rounding<nearest_even> : tile<f64>
      yield %18 : tile<f64>
    }
    %19 = constant <f64: 256.0> : tile<f64>
    %20 = divf %15, %19 rounding<nearest_even> : tile<f64>
    %21 = reshape %20 : tile<f64> -> tile<1xf64>
    %22 = broadcast %21 : tile<1xf64> -> tile<256xf64>
    %23 = subf %13, %22 rounding<nearest_even> : tile<256xf64>
    %24 = mulf %23, %23 rounding<nearest_even> : tile<256xf64>
    %25 = reduce %24 dim=0 identities=[0.0 : f64] : tile<256xf64> -> tile<f64> (%26: tile<f64>, %27: tile<f64>) {
      %28 = addf %26, %27 rounding<nearest_even> : tile<f64>
      yield %28 : tile<f64>
    }
    %29 = divf %25, %19 rounding<nearest_even> : tile<f64>
    %30 = constant <f64: 1.0E-5> : tile<f64>
    %31 = addf %29, %30 rounding<nearest_even> : tile<f64>
    %32 = sqrt %31 rounding<nearest_even> : tile<f64>
    %33 = reshape %32 : tile<f64> -> tile<1xf64>
    %34 = broadcast %33 : tile<1xf64> -> tile<256xf64>
    %35 = divf %23, %34 rounding<nearest_even> : tile<256xf64>
    %36 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %37 = make_tensor_view %36, shape = [256], strides = [1] : tensor_view<256xf64, strides=[1]>
    %38 = make_partition_view %37 : partition_view<tile=(256), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>
    %39, %40 = load_view_tko weak %38[%1] token=%14 : partition_view<tile=(256), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<256xf64>, token
    %41 = mulf %35, %39 rounding<nearest_even> : tile<256xf64>
    %42 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %43 = make_tensor_view %42, shape = [256], strides = [1] : tensor_view<256xf64, strides=[1]>
    %44 = make_partition_view %43 : partition_view<tile=(256), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>
    %45, %46 = load_view_tko weak %44[%1] token=%40 : partition_view<tile=(256), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<256xf64>, token
    %47 = addf %41, %45 rounding<nearest_even> : tile<256xf64>
    %48 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %49 = make_tensor_view %48, shape = [%6], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %50 = make_partition_view %49 : partition_view<tile=(256), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %51 = store_view_tko weak %47, %50[%10] token=%46 : tile<256xf64>, partition_view<tile=(256), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
