cuda_tile.module @m {
  entry @ols_gram(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = reshape %1 : tile<i32> -> tile<1x1xi32>
    %3 = broadcast %2 : tile<1x1xi32> -> tile<8x16xi32>
    %4 = iota : tile<8xi32>
    %5 = reshape %4 : tile<8xi32> -> tile<8x1xi32>
    %6 = broadcast %5 : tile<8x1xi32> -> tile<8x16xi32>
    %7 = constant <i32: 0> : tile<8x16xi32>
    %8 = muli %6, %7 : tile<8x16xi32>
    %9 = addi %3, %8 : tile<8x16xi32>
    %10 = iota : tile<16xi32>
    %11 = reshape %10 : tile<16xi32> -> tile<1x16xi32>
    %12 = broadcast %11 : tile<1x16xi32> -> tile<8x16xi32>
    %13 = addi %9, %12 : tile<8x16xi32>
    %14 = constant <i32: 8> : tile<8x16xi32>
    %15 = cmpi less_than %13, %14, signed : tile<8x16xi32> -> tile<8x16xi1>
    %16 = constant <i32: 8> : tile<8x16xi32>
    %17 = cmpi equal %13, %16, signed : tile<8x16xi32> -> tile<8x16xi1>
    %18 = constant <f64: 0.0> : tile<8x16xf64>
    %19 = constant <i32: 0> : tile<i32>
    %20 = constant <i32: 64> : tile<i32>
    %21 = constant <i32: 1> : tile<i32>
    %22 = for %23 in (%19 to %20, step %21) : tile<i32> iter_values(%24 = %18) -> (tile<8x16xf64>) {
      %25 = constant <i32: 8> : tile<i32>
      %26 = muli %23, %25 : tile<i32>
      %27 = reshape %26 : tile<i32> -> tile<1x1xi32>
      %28 = broadcast %27 : tile<1x1xi32> -> tile<8x16xi32>
      %29 = iota : tile<8xi32>
      %30 = reshape %29 : tile<8xi32> -> tile<8x1xi32>
      %31 = broadcast %30 : tile<8x1xi32> -> tile<8x16xi32>
      %32 = addi %28, %31 : tile<8x16xi32>
      %33 = iota : tile<16xi32>
      %34 = reshape %33 : tile<16xi32> -> tile<1x16xi32>
      %35 = broadcast %34 : tile<1x16xi32> -> tile<8x16xi32>
      %36 = constant <i32: 0> : tile<8x16xi32>
      %37 = muli %35, %36 : tile<8x16xi32>
      %38 = addi %32, %37 : tile<8x16xi32>
      %39 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %40 = broadcast %39 : tile<1x1xptr<f64>> -> tile<8x16xptr<f64>>
      %41 = offset %40, %38 : tile<8x16xptr<f64>>, tile<8x16xi32> -> tile<8x16xptr<f64>>
      %42, %43 = load_ptr_tko weak %41 token=%0 : tile<8x16xptr<f64>> -> tile<8x16xf64>, token
      %44 = constant <f64: 0.0> : tile<8x16xf64>
      %45 = reshape %26 : tile<i32> -> tile<1x1xi32>
      %46 = broadcast %45 : tile<1x1xi32> -> tile<8x16xi32>
      %47 = iota : tile<8xi32>
      %48 = reshape %47 : tile<8xi32> -> tile<8x1xi32>
      %49 = broadcast %48 : tile<8x1xi32> -> tile<8x16xi32>
      %50 = constant <i32: 0> : tile<8x16xi32>
      %51 = muli %49, %50 : tile<8x16xi32>
      %52 = addi %46, %51 : tile<8x16xi32>
      %53 = iota : tile<16xi32>
      %54 = reshape %53 : tile<16xi32> -> tile<1x16xi32>
      %55 = broadcast %54 : tile<1x16xi32> -> tile<8x16xi32>
      %56 = addi %52, %55 : tile<8x16xi32>
      %57 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %58 = broadcast %57 : tile<1x1xptr<f64>> -> tile<8x16xptr<f64>>
      %59 = offset %58, %56 : tile<8x16xptr<f64>>, tile<8x16xi32> -> tile<8x16xptr<f64>>
      %60, %61 = load_ptr_tko weak %59, %15, %44 token=%0 : tile<8x16xptr<f64>>, tile<8x16xi1>, tile<8x16xf64> -> tile<8x16xf64>, token
      %62 = reshape %23 : tile<i32> -> tile<1x1xi32>
      %63 = broadcast %62 : tile<1x1xi32> -> tile<8x16xi32>
      %64 = iota : tile<8xi32>
      %65 = reshape %64 : tile<8xi32> -> tile<8x1xi32>
      %66 = broadcast %65 : tile<8x1xi32> -> tile<8x16xi32>
      %67 = constant <i32: 0> : tile<8x16xi32>
      %68 = muli %66, %67 : tile<8x16xi32>
      %69 = addi %63, %68 : tile<8x16xi32>
      %70 = iota : tile<16xi32>
      %71 = reshape %70 : tile<16xi32> -> tile<1x16xi32>
      %72 = broadcast %71 : tile<1x16xi32> -> tile<8x16xi32>
      %73 = constant <i32: 0> : tile<8x16xi32>
      %74 = muli %72, %73 : tile<8x16xi32>
      %75 = addi %69, %74 : tile<8x16xi32>
      %76 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %77 = broadcast %76 : tile<1x1xptr<f64>> -> tile<8x16xptr<f64>>
      %78 = offset %77, %75 : tile<8x16xptr<f64>>, tile<8x16xi32> -> tile<8x16xptr<f64>>
      %79, %80 = load_ptr_tko weak %78 token=%0 : tile<8x16xptr<f64>> -> tile<8x16xf64>, token
      %81 = select %17, %79, %60 : tile<8x16xi1>, tile<8x16xf64>
      %82 = mulf %42, %81 rounding<nearest_even> : tile<8x16xf64>
      %83 = addf %24, %82 rounding<nearest_even> : tile<8x16xf64>
      continue %83 : tile<8x16xf64>
    }
    %84 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %85 = make_tensor_view %84, shape = [8, 16], strides = [16, 1] : tensor_view<8x16xf64, strides=[16, 1]>
    %86 = make_partition_view %85 : partition_view<tile=(8x16), padding_value = zero, tensor_view<8x16xf64, strides=[16, 1]>, dim_map=[0, 1]>
    %87, %88, %89 = get_tile_block_id : tile<i32>
    %90, %91, %92 = get_tile_block_id : tile<i32>
    %93 = store_view_tko weak %22, %86[%87, %91] token=%0 : tile<8x16xf64>, partition_view<tile=(8x16), padding_value = zero, tensor_view<8x16xf64, strides=[16, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
