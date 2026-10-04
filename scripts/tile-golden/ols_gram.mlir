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
    %22, %23 = for %24 in (%19 to %20, step %21) : tile<i32> iter_values(%25 = %18, %26 = %0) -> (tile<8x16xf64>, token) {
      %27 = constant <i32: 8> : tile<i32>
      %28 = muli %24, %27 : tile<i32>
      %29 = reshape %28 : tile<i32> -> tile<1x1xi32>
      %30 = broadcast %29 : tile<1x1xi32> -> tile<8x16xi32>
      %31 = iota : tile<8xi32>
      %32 = reshape %31 : tile<8xi32> -> tile<8x1xi32>
      %33 = broadcast %32 : tile<8x1xi32> -> tile<8x16xi32>
      %34 = addi %30, %33 : tile<8x16xi32>
      %35 = iota : tile<16xi32>
      %36 = reshape %35 : tile<16xi32> -> tile<1x16xi32>
      %37 = broadcast %36 : tile<1x16xi32> -> tile<8x16xi32>
      %38 = constant <i32: 0> : tile<8x16xi32>
      %39 = muli %37, %38 : tile<8x16xi32>
      %40 = addi %34, %39 : tile<8x16xi32>
      %41 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %42 = broadcast %41 : tile<1x1xptr<f64>> -> tile<8x16xptr<f64>>
      %43 = offset %42, %40 : tile<8x16xptr<f64>>, tile<8x16xi32> -> tile<8x16xptr<f64>>
      %44, %45 = load_ptr_tko weak %43 token=%26 : tile<8x16xptr<f64>> -> tile<8x16xf64>, token
      %46 = constant <f64: 0.0> : tile<8x16xf64>
      %47 = reshape %28 : tile<i32> -> tile<1x1xi32>
      %48 = broadcast %47 : tile<1x1xi32> -> tile<8x16xi32>
      %49 = iota : tile<8xi32>
      %50 = reshape %49 : tile<8xi32> -> tile<8x1xi32>
      %51 = broadcast %50 : tile<8x1xi32> -> tile<8x16xi32>
      %52 = constant <i32: 0> : tile<8x16xi32>
      %53 = muli %51, %52 : tile<8x16xi32>
      %54 = addi %48, %53 : tile<8x16xi32>
      %55 = iota : tile<16xi32>
      %56 = reshape %55 : tile<16xi32> -> tile<1x16xi32>
      %57 = broadcast %56 : tile<1x16xi32> -> tile<8x16xi32>
      %58 = addi %54, %57 : tile<8x16xi32>
      %59 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %60 = broadcast %59 : tile<1x1xptr<f64>> -> tile<8x16xptr<f64>>
      %61 = offset %60, %58 : tile<8x16xptr<f64>>, tile<8x16xi32> -> tile<8x16xptr<f64>>
      %62, %63 = load_ptr_tko weak %61, %15, %46 token=%45 : tile<8x16xptr<f64>>, tile<8x16xi1>, tile<8x16xf64> -> tile<8x16xf64>, token
      %64 = reshape %24 : tile<i32> -> tile<1x1xi32>
      %65 = broadcast %64 : tile<1x1xi32> -> tile<8x16xi32>
      %66 = iota : tile<8xi32>
      %67 = reshape %66 : tile<8xi32> -> tile<8x1xi32>
      %68 = broadcast %67 : tile<8x1xi32> -> tile<8x16xi32>
      %69 = constant <i32: 0> : tile<8x16xi32>
      %70 = muli %68, %69 : tile<8x16xi32>
      %71 = addi %65, %70 : tile<8x16xi32>
      %72 = iota : tile<16xi32>
      %73 = reshape %72 : tile<16xi32> -> tile<1x16xi32>
      %74 = broadcast %73 : tile<1x16xi32> -> tile<8x16xi32>
      %75 = constant <i32: 0> : tile<8x16xi32>
      %76 = muli %74, %75 : tile<8x16xi32>
      %77 = addi %71, %76 : tile<8x16xi32>
      %78 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %79 = broadcast %78 : tile<1x1xptr<f64>> -> tile<8x16xptr<f64>>
      %80 = offset %79, %77 : tile<8x16xptr<f64>>, tile<8x16xi32> -> tile<8x16xptr<f64>>
      %81, %82 = load_ptr_tko weak %80 token=%63 : tile<8x16xptr<f64>> -> tile<8x16xf64>, token
      %83 = select %17, %81, %62 : tile<8x16xi1>, tile<8x16xf64>
      %84 = mulf %44, %83 rounding<nearest_even> : tile<8x16xf64>
      %85 = addf %25, %84 rounding<nearest_even> : tile<8x16xf64>
      continue %85, %82 : tile<8x16xf64>, token
    }
    %86 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %87 = make_tensor_view %86, shape = [8, 16], strides = [16, 1] : tensor_view<8x16xf64, strides=[16, 1]>
    %88 = make_partition_view %87 : partition_view<tile=(8x16), padding_value = zero, tensor_view<8x16xf64, strides=[16, 1]>, dim_map=[0, 1]>
    %89, %90, %91 = get_tile_block_id : tile<i32>
    %92, %93, %94 = get_tile_block_id : tile<i32>
    %95 = store_view_tko weak %22, %88[%89, %93] token=%23 : tile<8x16xf64>, partition_view<tile=(8x16), padding_value = zero, tensor_view<8x16xf64, strides=[16, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
