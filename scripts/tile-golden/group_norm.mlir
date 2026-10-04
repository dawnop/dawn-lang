cuda_tile.module @m {
  entry @group_norm(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [2, 8, 32], strides = [256, 32, 1] : tensor_view<2x8x32xf64, strides=[256, 32, 1]>
    %3 = make_partition_view %2 : partition_view<tile=(1x2x32), padding_value = zero, tensor_view<2x8x32xf64, strides=[256, 32, 1]>, dim_map=[0, 1, 2]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10, %11, %12 = get_tile_block_id : tile<i32>
    %13, %14 = load_view_tko weak %3[%4, %8, %12] token=%0 : partition_view<tile=(1x2x32), padding_value = zero, tensor_view<2x8x32xf64, strides=[256, 32, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x2x32xf64>, token
    %15 = constant <i32: 0> : tile<i32>
    %16 = constant <i32: 0> : tile<i32>
    %17 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %18 = make_tensor_view %17, shape = [1, 8, 1], strides = [8, 1, 1] : tensor_view<1x8x1xf64, strides=[8, 1, 1]>
    %19 = make_partition_view %18 : partition_view<tile=(1x2x1), padding_value = zero, tensor_view<1x8x1xf64, strides=[8, 1, 1]>, dim_map=[0, 1, 2]>
    %20, %21 = load_view_tko weak %19[%15, %8, %16] token=%14 : partition_view<tile=(1x2x1), padding_value = zero, tensor_view<1x8x1xf64, strides=[8, 1, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x2x1xf64>, token
    %22 = broadcast %20 : tile<1x2x1xf64> -> tile<1x2x32xf64>
    %23 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %24 = make_tensor_view %23, shape = [1, 8, 1], strides = [8, 1, 1] : tensor_view<1x8x1xf64, strides=[8, 1, 1]>
    %25 = make_partition_view %24 : partition_view<tile=(1x2x1), padding_value = zero, tensor_view<1x8x1xf64, strides=[8, 1, 1]>, dim_map=[0, 1, 2]>
    %26, %27 = load_view_tko weak %25[%15, %8, %16] token=%21 : partition_view<tile=(1x2x1), padding_value = zero, tensor_view<1x8x1xf64, strides=[8, 1, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x2x1xf64>, token
    %28 = broadcast %26 : tile<1x2x1xf64> -> tile<1x2x32xf64>
    %29 = reduce %13 dim=2 identities=[0.0 : f64] : tile<1x2x32xf64> -> tile<1x2xf64> (%30: tile<f64>, %31: tile<f64>) {
      %32 = addf %30, %31 rounding<nearest_even> : tile<f64>
      yield %32 : tile<f64>
    }
    %33 = reduce %29 dim=1 identities=[0.0 : f64] : tile<1x2xf64> -> tile<1xf64> (%34: tile<f64>, %35: tile<f64>) {
      %36 = addf %34, %35 rounding<nearest_even> : tile<f64>
      yield %36 : tile<f64>
    }
    %37 = reduce %33 dim=0 identities=[0.0 : f64] : tile<1xf64> -> tile<f64> (%38: tile<f64>, %39: tile<f64>) {
      %40 = addf %38, %39 rounding<nearest_even> : tile<f64>
      yield %40 : tile<f64>
    }
    %41 = constant <f64: 64.0> : tile<f64>
    %42 = divf %37, %41 rounding<nearest_even> : tile<f64>
    %43 = reshape %42 : tile<f64> -> tile<1x1x1xf64>
    %44 = broadcast %43 : tile<1x1x1xf64> -> tile<1x2x32xf64>
    %45 = subf %13, %44 rounding<nearest_even> : tile<1x2x32xf64>
    %46 = mulf %45, %45 rounding<nearest_even> : tile<1x2x32xf64>
    %47 = reduce %46 dim=2 identities=[0.0 : f64] : tile<1x2x32xf64> -> tile<1x2xf64> (%48: tile<f64>, %49: tile<f64>) {
      %50 = addf %48, %49 rounding<nearest_even> : tile<f64>
      yield %50 : tile<f64>
    }
    %51 = reduce %47 dim=1 identities=[0.0 : f64] : tile<1x2xf64> -> tile<1xf64> (%52: tile<f64>, %53: tile<f64>) {
      %54 = addf %52, %53 rounding<nearest_even> : tile<f64>
      yield %54 : tile<f64>
    }
    %55 = reduce %51 dim=0 identities=[0.0 : f64] : tile<1xf64> -> tile<f64> (%56: tile<f64>, %57: tile<f64>) {
      %58 = addf %56, %57 rounding<nearest_even> : tile<f64>
      yield %58 : tile<f64>
    }
    %59 = divf %55, %41 rounding<nearest_even> : tile<f64>
    %60 = constant <f64: 1.0E-5> : tile<f64>
    %61 = addf %59, %60 rounding<nearest_even> : tile<f64>
    %62 = sqrt %61 rounding<nearest_even> : tile<f64>
    %63 = reshape %62 : tile<f64> -> tile<1x1x1xf64>
    %64 = broadcast %63 : tile<1x1x1xf64> -> tile<1x2x32xf64>
    %65 = divf %45, %64 rounding<nearest_even> : tile<1x2x32xf64>
    %66 = mulf %65, %22 rounding<nearest_even> : tile<1x2x32xf64>
    %67 = addf %66, %28 rounding<nearest_even> : tile<1x2x32xf64>
    %68 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %69 = make_tensor_view %68, shape = [2, 8, 32], strides = [256, 32, 1] : tensor_view<2x8x32xf64, strides=[256, 32, 1]>
    %70 = make_partition_view %69 : partition_view<tile=(1x2x32), padding_value = zero, tensor_view<2x8x32xf64, strides=[256, 32, 1]>, dim_map=[0, 1, 2]>
    %71 = store_view_tko weak %67, %70[%4, %8, %12] token=%27 : tile<1x2x32xf64>, partition_view<tile=(1x2x32), padding_value = zero, tensor_view<2x8x32xf64, strides=[256, 32, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    return
  }
}
